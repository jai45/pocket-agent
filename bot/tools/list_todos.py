"""List the chat's open to-dos."""

from datetime import date

from bot import db, timeutil
from bot.tool_context import ToolContext

FILTERS = ("today", "all", "overdue")
PRIORITY_ORDER = {"high": 0, "med": 1, "low": 2}

SPEC = {
    "name": "list_todos",
    "description": (
        "List the user's open (not completed) to-dos with ids, due dates and "
        "priorities. filter: 'today' = due today or overdue, 'overdue' = past due, "
        "'all' = every open item. Use this, not conversation memory, whenever asked "
        "what to-dos exist. Use before complete_todo if you don't know the id."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"filter": {"type": "string", "enum": list(FILTERS), "description": "Default 'all'."}},
    },
}


def _sort_key(row) -> tuple:
    """High priority first, then soonest due (no date last), then oldest."""
    return (PRIORITY_ORDER[row["priority"]], row["due_date"] or "9999-12-31", row["id"])


def list_todos(ctx: ToolContext, filter: str = "all") -> dict:  # noqa: A002 - matches the tool schema
    """Filter against the user's local 'today', not UTC's."""
    if filter not in FILTERS:
        return {"error": f"filter must be one of {', '.join(FILTERS)}"}
    today = timeutil.local_today()
    rows = db.get_conn().execute(
        "SELECT * FROM todos WHERE chat_id = ? AND done_at IS NULL", (ctx.chat_id,)
    ).fetchall()

    items = []
    for row in sorted(rows, key=_sort_key):
        due = date.fromisoformat(row["due_date"]) if row["due_date"] else None
        overdue = due is not None and due < today
        if filter == "overdue" and not overdue:
            continue
        if filter == "today" and not (due is not None and due <= today):
            continue
        items.append({
            "id": row["id"],
            "text": row["text"],
            "due": timeutil.format_date(due) if due else None,
            "priority": row["priority"],
            "overdue": overdue,
        })
    result = {"filter": filter, "today": timeutil.format_date(today), "todos": items}
    if not items:
        result["note"] = "nothing to show"
    return result
