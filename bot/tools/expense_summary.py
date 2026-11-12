"""Summarise spending over a period."""

from datetime import date, timedelta

from bot import db, money, timeutil
from bot.tool_context import ToolContext

PERIODS = ("week", "month", "custom")
GROUPS = ("category", "day")
MAX_ITEMS = 50

SPEC = {
    "name": "expense_summary",
    "description": (
        "Total the user's expenses for a period, grouped by category or by day, "
        "with the 3 biggest single expenses. period: 'week' = this calendar week "
        "from Monday, 'month' = this month so far, 'custom' = start_date..end_date "
        "(use for 'last month', 'October', 'last 30 days'; call get_current_time "
        "first). Report the totals it returns; never add amounts up yourself. Set "
        "include_items=true to list individual expenses with ids (needed before "
        "delete_expense)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "period": {"type": "string", "enum": list(PERIODS), "description": "Default 'month'."},
            "group_by": {"type": "string", "enum": list(GROUPS), "description": "Default 'category'."},
            "start_date": {"type": "string", "description": "YYYY-MM-DD, required for custom."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD, required for custom (inclusive)."},
            "include_items": {"type": "boolean", "description": f"Also list up to {MAX_ITEMS} expenses with ids."},
        },
    },
}


def _date_range(period: str, start_date: str | None, end_date: str | None) -> tuple[date, date]:
    """Resolve the period to an inclusive (start, end) in the user's local dates."""
    today = timeutil.local_today()
    if period == "week":
        return today - timedelta(days=today.weekday()), today
    if period == "month":
        return today.replace(day=1), today
    if not (start_date and end_date):
        raise ValueError("custom period needs start_date and end_date")
    start, end = date.fromisoformat(start_date.strip()), date.fromisoformat(end_date.strip())
    if start > end:
        raise ValueError("start_date is after end_date")
    return start, end


def _item(row) -> dict:
    return {
        "id": row["id"],
        "amount": money.format_money(row["amount_cents"]),
        "category": row["category"],
        "note": row["note"],
        "date": timeutil.format_date(date.fromisoformat(row["spent_on"])),
    }


def expense_summary(
    ctx: ToolContext,
    period: str = "month",
    group_by: str = "category",
    start_date: str | None = None,
    end_date: str | None = None,
    include_items: bool = False,
) -> dict:
    """Sums are done in SQL on integer cents, so totals are exact."""
    if period not in PERIODS:
        return {"error": f"period must be one of {', '.join(PERIODS)}"}
    if group_by not in GROUPS:
        return {"error": f"group_by must be one of {', '.join(GROUPS)}"}
    try:
        start, end = _date_range(period, start_date, end_date)
    except ValueError as exc:
        return {"error": str(exc)}

    conn = db.get_conn()
    where = "chat_id = ? AND spent_on BETWEEN ? AND ?"
    params = (ctx.chat_id, start.isoformat(), end.isoformat())
    total, count = conn.execute(
        f"SELECT COALESCE(SUM(amount_cents), 0), COUNT(*) FROM expenses WHERE {where}", params
    ).fetchone()

    result: dict = {
        "period": f"{timeutil.format_date(start)} – {timeutil.format_date(end)}",
        "total": money.format_money(total),
        "count": count,
    }
    if group_by == "category":
        rows = conn.execute(
            f"SELECT category, SUM(amount_cents) AS cents, COUNT(*) AS n FROM expenses "
            f"WHERE {where} GROUP BY category ORDER BY cents DESC",
            params,
        ).fetchall()
        result["by_category"] = [
            {"category": r["category"], "total": money.format_money(r["cents"]), "count": r["n"]} for r in rows
        ]
    else:
        rows = conn.execute(
            f"SELECT spent_on, SUM(amount_cents) AS cents FROM expenses "
            f"WHERE {where} GROUP BY spent_on ORDER BY spent_on",
            params,
        ).fetchall()
        result["by_day"] = [
            {"date": timeutil.format_date(date.fromisoformat(r["spent_on"])), "total": money.format_money(r["cents"])}
            for r in rows
        ]
    top = conn.execute(
        f"SELECT * FROM expenses WHERE {where} ORDER BY amount_cents DESC, id LIMIT 3", params
    ).fetchall()
    result["top_items"] = [_item(r) for r in top]
    if include_items:
        rows = conn.execute(
            f"SELECT * FROM expenses WHERE {where} ORDER BY spent_on DESC, id DESC LIMIT ?",
            (*params, MAX_ITEMS),
        ).fetchall()
        result["items"] = [_item(r) for r in rows]
    if count == 0:
        result["note"] = "no expenses in this period"
    return result
