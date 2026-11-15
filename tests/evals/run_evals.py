"""Run the behaviour evals in cases.yaml against the REAL Anthropic API.

    python -m tests.evals.run_evals                    # all cases once
    python -m tests.evals.run_evals --only bought_groceries,todo_with_due_date --repeat 3
    python -m tests.evals.run_evals --tag web          # only cases tagged 'web'
    python -m tests.evals.run_evals --live-network     # real weather/news/search/pages

Unit tests check that tools work; evals check that the model CHOOSES the
right tools. Every case gets a fresh temporary database, so cases can't
leak into each other or into data/pocket.db. Network tools return canned
results by default, so a failure means the model behaved differently, not
that a website was down. Model output varies between runs: use --repeat to
tell a real change from noise. Not collected by pytest (it costs money).
"""

import argparse
import asyncio
import logging
import re
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

import yaml

from bot import config, db, history, memory, reminders, timeutil, usage
from bot.agent import run_agent
from bot.tool_context import ToolContext
from bot.tools import _FUNCTIONS
from bot.tools.add_expense import add_expense
from bot.tools.add_grocery_items import add_grocery_items
from bot.tools.add_todo import add_todo
from bot.tools.save_note import save_note
from bot.tools.set_reminder import set_reminder

CASES_FILE = Path(__file__).with_name("cases.yaml")
CHAT_ID = 1
CTX = ToolContext(CHAT_ID)


# --- Canned network tools --------------------------------------------------

DEFAULT_RESULTS = [
    {"title": "Race report: Driver A wins the latest Grand Prix", "url": "https://example.com/race",
     "snippet": "Driver A took victory ahead of Driver B and Driver C.", "age": "2 days ago"},
]
DEFAULT_PAGE = "Race report: Driver A won the latest Grand Prix, ahead of Driver B."
URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


def stub_network(setup: dict) -> None:
    """Swap the four network tools in the registry for offline fakes.

    A case can shape them: `search_results` (what web_search returns),
    `search_error` (web_search fails), and `pages` (url -> text, or
    {error: ...} for a dead link; unknown URLs get a generic page).
    """
    pages = setup.get("pages", {})
    results = setup.get("search_results", DEFAULT_RESULTS)

    async def get_weather(location: str | None = None, days: int = 1, **_) -> dict:
        return {"location": location or "Lisbon, Portugal", "today": {
            "summary": "rain showers", "high_c": 17, "low_c": 11, "rain_chance_pct": 80}}

    async def get_news(topic: str, max_items: int = 5, **_) -> dict:
        return {"topic": topic, "items": [
            {"title": "Chipmaker unveils faster laptop processor", "source": "Ars Technica", "url": "https://example.com/n1"},
            {"title": "Open-source browser ships new privacy features", "source": "The Verge", "url": "https://example.com/n2"},
            {"title": "Researchers demo low-power AI accelerator", "source": "Hacker News", "url": "https://example.com/n3"},
        ]}

    async def web_search(query: str, max_results: int = 5, freshness: str | None = None, **_) -> dict:
        if setup.get("search_error"):
            return {"error": setup["search_error"]}
        return {"query": query, "results": results[: max(1, min(int(max_results), 10))]}

    async def fetch_url(url: str, **_) -> dict:
        page = pages.get(url, DEFAULT_PAGE)
        if isinstance(page, dict):
            return {"error": page.get("error", "could not fetch")}
        return {"url": url, "title": "Example page", "text": page, "truncated": False}

    for fn in (get_weather, get_news, web_search, fetch_url):
        _FUNCTIONS[fn.__name__] = fn


def known_urls(case: dict) -> set[str]:
    """URLs the model was legitimately given: in the message or in search results."""
    setup = case.get("setup", {})
    urls = set(URL_RE.findall(case["message"]))
    urls |= {r["url"] for r in setup.get("search_results", DEFAULT_RESULTS)}
    return urls


# --- Setup -----------------------------------------------------------------

def apply_setup(setup: dict) -> None:
    """Create the data a case assumes already exists, using the real tool code."""
    for fact in setup.get("facts", []):
        memory.add_fact(CHAT_ID, fact)
    for text in setup.get("todos", []):
        add_todo(text, CTX)
    for item in setup.get("reminders", []):
        when = timeutil.utc_now() + timedelta(hours=item.get("in_hours", 24))
        set_reminder(item["text"], when.isoformat(), CTX)
    if setup.get("groceries"):
        add_grocery_items(setup["groceries"], CTX)
    for note in setup.get("notes", []):
        save_note(note["title"], note["content"], CTX, tags=note.get("tags"))
    for exp in setup.get("expenses", []):
        add_expense(exp["amount"], exp["category"], exp.get("note", ""), CTX)
    for user_text, reply in setup.get("history", []):
        history.add_exchange(CHAT_ID, user_text, reply)


# --- Checking --------------------------------------------------------------

def _norm(url: str) -> str:
    return url.rstrip("/.,")


def check(expect: dict, calls: list[tuple[str, dict]], reply: str, known: set[str] | None = None) -> list[str]:
    """Return the reasons a case failed (empty list = pass).

    `calls` is [(tool name, tool input), ...] in order, so we can check the
    path the agent took (which URLs, which arguments), not just the reply.
    """
    problems = []
    tools = [name for name, _ in calls]
    fetched = [_norm(str(inp.get("url", ""))) for name, inp in calls if name == "fetch_url"]
    lower = reply.lower()

    for name in expect.get("tools_called", []):
        if name not in tools:
            problems.append(f"expected {name} to be called")
    for name in expect.get("tools_not_called", []):
        if name in tools:
            problems.append(f"{name} should NOT be called")
    for name, limits in expect.get("tool_counts", {}).items():
        n = tools.count(name)
        if n < limits.get("min", 0) or n > limits.get("max", 10**6):
            problems.append(f"{name} called {n}x, expected {limits.get('min', 0)}..{limits.get('max', 'any')}")
    for rule in expect.get("tool_args", []):
        values = [inp.get(rule["arg"]) for name, inp in calls if name == rule["tool"]]
        if not any(v in rule["in"] for v in values):
            problems.append(f"{rule['tool']}.{rule['arg']} was {values}, expected one of {rule['in']}")
    for url in expect.get("urls_fetched", []):
        if _norm(url) not in fetched:
            problems.append(f"expected {url} to be fetched")
    for part in expect.get("urls_not_fetched", []):
        if any(part in u for u in fetched):
            problems.append(f"fetched a URL containing {part!r}")
    if expect.get("fetch_only_known_urls"):
        allowed = {_norm(u) for u in (known or set())}
        for url in fetched:
            if url not in allowed:
                problems.append(f"fetched a URL it wasn't given: {url}")
    for text in expect.get("reply_contains", []):
        if str(text).lower() not in lower:
            problems.append(f"reply missing {text!r}")
    any_of = expect.get("reply_contains_any", [])
    if any_of and not any(str(t).lower() in lower for t in any_of):
        problems.append(f"reply has none of {any_of}")
    for text in expect.get("reply_not_contains", []):
        if str(text).lower() in lower:
            problems.append(f"reply contains {text!r}")
    return problems


async def run_case(case: dict, workdir: Path, n: int, live_network: bool) -> tuple[bool, list[str], float]:
    """One case on a fresh DB; return (passed, reasons, cost_usd)."""
    db.init(workdir / f"eval-{n}.db")
    reminders.attach(None)  # no Telegram job queue: reminders are saved, not scheduled
    if not live_network:
        stub_network(case.get("setup", {}))
    apply_setup(case.get("setup", {}))
    try:
        result = await run_agent(CHAT_ID, case["message"], trigger="eval")
        calls = [(c.name, c.input) for c in result.trace]
        problems = check(case.get("expect", {}), calls, result.text, known_urls(case))
        detail = "tools=" + ", ".join(
            f"{n}({i.get('url') or i.get('query') or ''})" if n in ("fetch_url", "web_search") else n
            for n, i in calls
        )
        reply = result.text.replace("\n", " ")
        detail += f" reply={reply[:120]!r}"
    except Exception as exc:  # noqa: BLE001 - a crash is a failed case, not a dead run
        problems, detail = [f"crashed: {exc.__class__.__name__}: {exc}"], ""
    today = timeutil.local_today()
    cost = usage.spent(today - timedelta(days=1), today + timedelta(days=1))
    db.close()
    return not problems, problems + ([detail] if problems else []), cost


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--tag", help="only cases with this tag, e.g. web")
    parser.add_argument("--repeat", type=int, default=1, help="run each case N times")
    parser.add_argument("--live-network", action="store_true", help="don't stub weather/news/search/pages")
    parser.add_argument("--verbose", action="store_true", help="show tools for passing cases too")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)  # keep per-call INFO lines out of the report
    cases = yaml.safe_load(CASES_FILE.read_text())
    if args.tag:
        cases = [c for c in cases if args.tag in c.get("tags", [])]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    if not cases:
        print("No cases match the filters")
        return 2

    passed = total = 0
    cost = 0.0
    start = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        config.LOG_DIR = workdir / "logs"  # eval runs stay out of data/logs
        n = 0
        for case in cases:
            results = []
            for _ in range(args.repeat):
                n += 1
                ok, reasons, case_cost = await run_case(case, workdir, n, args.live_network)
                results.append(ok)
                cost += case_cost
                passed += ok
                total += 1
                if not ok:
                    print(f"  FAIL {case['id']}: " + "; ".join(reasons))
            mark = "PASS" if all(results) else "FAIL"
            print(f"{mark} {case['id']} ({sum(results)}/{len(results)})", flush=True)

    elapsed = time.perf_counter() - start
    print(f"\nPass rate: {passed}/{total} = {passed / total:.0%}   "
          f"cost ≈ ${cost:.3f}   time {elapsed:.0f}s   model {config.DEFAULT_MODEL}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
