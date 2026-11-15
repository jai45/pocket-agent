"""Token usage, estimated cost, and the daily budget.

Every model call is recorded here by llm.create, so /cost, the budget and
the eval runner all read from one table instead of re-adding log lines.
Costs are estimates from config.MODEL_PRICES; the Anthropic console is the
real bill.
"""

import logging
from datetime import date

from bot import config, db, timeutil

logger = logging.getLogger(__name__)

OK, FAST, BLOCKED = "ok", "fast", "blocked"


def prices_for(model: str) -> dict[str, float]:
    """Price row for a model id. Prefix match, so 'claude-haiku-5-5-2026…' works.

    An unknown model is priced like the most expensive one we know, so a
    typo in .env makes the budget trip early rather than never.
    """
    for prefix, prices in config.MODEL_PRICES.items():
        if model.startswith(prefix):
            return prices
    logger.warning("No price for model %s; using the highest known prices", model)
    return max(config.MODEL_PRICES.values(), key=lambda p: p["output"])


def cost_usd(model: str, input_tokens: int, output_tokens: int,
             cache_read: int = 0, cache_write: int = 0) -> float:
    """Estimated USD for one call. input_tokens excludes cached tokens (as the API reports it)."""
    p = prices_for(model)
    return (
        input_tokens * p["input"]
        + output_tokens * p["output"]
        + cache_read * p["cache_read"]
        + cache_write * p["cache_write"]
    ) / 1_000_000


def tokens_of(api_usage) -> tuple[int, int, int, int]:
    """(input, output, cache_read, cache_write) from a response.usage; None counts as 0."""
    return (
        api_usage.input_tokens or 0,
        api_usage.output_tokens or 0,
        getattr(api_usage, "cache_read_input_tokens", 0) or 0,
        getattr(api_usage, "cache_creation_input_tokens", 0) or 0,
    )


def record(model: str, api_usage) -> float:
    """Save one call's usage; return its estimated cost."""
    inp, out, cread, cwrite = tokens_of(api_usage)
    cost = cost_usd(model, inp, out, cread, cwrite)
    conn = db.get_conn()
    with conn:
        conn.execute(
            "INSERT INTO usage (local_date, model, input_tokens, output_tokens, "
            "cache_read_tokens, cache_write_tokens, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (timeutil.local_today().isoformat(), model, inp, out, cread, cwrite, cost),
        )
    return cost


def totals(start: date, end: date) -> list[dict]:
    """Per-model sums for local dates start..end inclusive."""
    rows = db.get_conn().execute(
        "SELECT model, COUNT(*) AS calls, SUM(input_tokens) AS input, SUM(output_tokens) AS output, "
        "SUM(cache_read_tokens) AS cache_read, SUM(cache_write_tokens) AS cache_write, "
        "SUM(cost_usd) AS cost FROM usage WHERE local_date BETWEEN ? AND ? "
        "GROUP BY model ORDER BY cost DESC",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    return [dict(r) for r in rows]


def spent(start: date, end: date) -> float:
    return sum(r["cost"] for r in totals(start, end))


def spent_today() -> float:
    today = timeutil.local_today()
    return spent(today, today)


def budget_state() -> str:
    """OK, FAST (>= 1x budget: use the cheap model) or BLOCKED (>= 2x: refuse chat)."""
    budget = config.DAILY_BUDGET_USD
    if budget <= 0:
        return OK
    today = spent_today()
    if today >= 2 * budget:
        return BLOCKED
    if today >= budget:
        return FAST
    return OK


def cache_savings(rows: list[dict]) -> float:
    """What cache reads saved versus paying the full input price for those tokens."""
    return sum(
        r["cache_read"] * (prices_for(r["model"])["input"] - prices_for(r["model"])["cache_read"])
        for r in rows
    ) / 1_000_000


def _period_lines(label: str, rows: list[dict]) -> list[str]:
    total = sum(r["cost"] for r in rows)
    calls = sum(r["calls"] for r in rows)
    lines = [f"{label}: ${total:.4f} ({calls} calls)"]
    for r in rows:
        lines.append(
            f"  • {r['model']}: ${r['cost']:.4f}, {r['calls']} calls, "
            f"in {r['input']:,} / out {r['output']:,} / cache read {r['cache_read']:,} "
            f"/ cache write {r['cache_write']:,}"
        )
    saved = cache_savings(rows)
    if saved > 0:
        lines.append(f"  • caching saved about ${saved:.4f}")
    return lines


def cost_report() -> str:
    """The /cost message: today, month to date, and the budget status."""
    today = timeutil.local_today()
    lines = ["💰 Estimated API spend"]
    lines += _period_lines("Today", totals(today, today))
    lines += _period_lines("This month", totals(today.replace(day=1), today))
    budget = config.DAILY_BUDGET_USD
    if budget > 0:
        state = budget_state()
        status = {OK: "normal", FAST: "over budget: using the fast model",
                  BLOCKED: "2x over budget: chat paused until tomorrow"}[state]
        lines.append(f"Daily budget: ${budget:.2f} ({status})")
    else:
        lines.append("Daily budget: not set (DAILY_BUDGET_USD in .env)")
    return "\n".join(lines)
