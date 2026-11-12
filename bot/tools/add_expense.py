"""Record money the user spent."""

from datetime import date as Date

from bot import db, money, timeutil
from bot.tool_context import ToolContext

CATEGORIES = ("food", "transport", "shopping", "bills", "fun", "other")

SPEC = {
    "name": "add_expense",
    "description": (
        "Record an expense the user tells you about ('spent 12.50 on lunch'). You "
        "pick the category: food (groceries, restaurants, coffee), transport (fuel, "
        "taxis, transit), shopping (clothes, gadgets, household), bills (rent, "
        "utilities, phone, subscriptions), fun (movies, games, outings), or other. "
        "Leave date out for today; for 'yesterday' etc. call get_current_time first. "
        "Do not use it for income or for amounts the user is only thinking about."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "amount": {"type": "number", "description": "Amount spent, e.g. 12.5. Positive."},
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "note": {"type": "string", "description": "Short description, e.g. 'lunch with Sam'."},
            "date": {"type": "string", "description": "Optional local date YYYY-MM-DD. Default today."},
        },
        "required": ["amount", "category", "note"],
    },
}


def add_expense(amount: float, category: str, note: str, ctx: ToolContext, date: str | None = None) -> dict:  # noqa: A002
    """Validate and save; amounts are stored as whole cents."""
    if category not in CATEGORIES:
        return {"error": f"category must be one of {', '.join(CATEGORIES)}"}
    try:
        cents = money.to_cents(amount)
    except ValueError as exc:
        return {"error": str(exc)}
    today = timeutil.local_today()
    spent_on = today
    if date:
        try:
            spent_on = _parse_date(date)
        except ValueError:
            return {"error": f"could not parse date {date!r}; use YYYY-MM-DD"}
        if spent_on > today:
            return {"error": f"date is in the future (today is {timeutil.format_date(today)})"}

    conn = db.get_conn()
    with conn:
        cur = conn.execute(
            "INSERT INTO expenses (chat_id, amount_cents, category, note, spent_on) VALUES (?, ?, ?, ?, ?)",
            (ctx.chat_id, cents, category, note.strip(), spent_on.isoformat()),
        )
    return {
        "id": cur.lastrowid,
        "amount": money.format_money(cents),
        "category": category,
        "note": note.strip(),
        "date": timeutil.format_date(spent_on),
    }


def _parse_date(value: str) -> Date:
    """The tool's `date` parameter shadows datetime.date, hence the alias."""
    return Date.fromisoformat(value.strip())
