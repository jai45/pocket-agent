"""Run the behaviour evals in cases.yaml against the REAL Anthropic API.

    python -m tests.evals.run_evals                    # all cases once
    python -m tests.evals.run_evals --only bought_groceries,todo_with_due_date --repeat 3
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

def stub_network(pages: dict[str, str]) -> None:
    """Swap the four network tools in the registry for offline fakes."""

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
        return {"query": query, "results": [
            {"title": "Race report: Driver A wins the latest Grand Prix", "url": "https://example.com/race",
             "snippet": "Driver A took victory ahead of Driver B and Driver C.", "age": "2 days ago"},
        ]}

    async def fetch_url(url: str, **_) -> dict:
        text = pages.get(url, "Race report: Driver A won the latest Grand Prix, ahead of Driver B.")
        return {"url": url, "title": "Example page", "text": text, "truncated": False}

    for fn in (get_weather, get_news, web_search, fetch_url):
        _FUNCTIONS[fn.__name__] = fn


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

def check(expect: dict, tools: list[str], reply: str) -> list[str]:
    """Return the reasons a case failed (empty list = pass)."""
    problems = []
    lower = reply.lower()
    for name in expect.get("tools_called", []):
        if name not in tools:
            problems.append(f"expected {name} to be called")
    for name in expect.get("tools_not_called", []):
        if name in tools:
            problems.append(f"{name} should NOT be called")
    for text in expect.get("reply_contains", []):
        if str(text).lower() not in lower:
            problems.append(f"reply missing {text!r}")
    for text in expect.get("reply_not_contains", []):
        if str(text).lower() in lower:
            problems.append(f"reply contains {text!r}")
    return problems


async def run_case(case: dict, workdir: Path, n: int, live_network: bool) -> tuple[bool, list[str], float]:
    """One case on a fresh DB; return (passed, reasons, cost_usd)."""
    db.init(workdir / f"eval-{n}.db")
    reminders.attach(None)  # no Telegram job queue: reminders are saved, not scheduled
    if not live_network:
        stub_network(case.get("setup", {}).get("pages", {}))
    apply_setup(case.get("setup", {}))
    try:
        result = await run_agent(CHAT_ID, case["message"], trigger="eval")
        tools = [c.name for c in result.trace]
        problems = check(case.get("expect", {}), tools, result.text)
        detail = f"tools={tools}"
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
    parser.add_argument("--repeat", type=int, default=1, help="run each case N times")
    parser.add_argument("--live-network", action="store_true", help="don't stub weather/news/search/pages")
    parser.add_argument("--verbose", action="store_true", help="show tools for passing cases too")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)  # keep per-call INFO lines out of the report
    cases = yaml.safe_load(CASES_FILE.read_text())
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
        if not cases:
            print(f"No cases match {args.only}")
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
