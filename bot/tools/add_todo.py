"""Add an item to the chat's to-do list."""

from datetime import date

from bot import db, timeutil
from bot.tool_context import ToolContext

PRIORITIES = ("low", "med", "high")

SPEC = {
    "name": "add_todo",
    "description": (
        "Add a task to the user's to-do list, optionally with a due date and priority. "
        "Use for things to do that don't need a message at a specific time. If the "
        "user gives a relative date ('by Friday'), call get_current_time first. "
        "If they want to be pinged at a time, use set_reminder instead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The task, e.g. 'renew passport'."},
            "due_date": {"type": "string", "description": "Optional local date, YYYY-MM-DD."},
            "priority": {"type": "string", "enum": list(PRIORITIES), "description": "Default 'med'."},
        },
        "required": ["text"],
    },
}


def add_todo(text: str, ctx: ToolContext, due_date: str | None = None, priority: str = "med") -> dict:
    """Save the to-do. Due dates are calendar dates, so they are NOT converted to UTC."""
    text = text.strip()
    if not text:
        return {"error": "to-do text is empty"}
    if priority not in PRIORITIES:
        return {"error": f"priority must be one of {', '.join(PRIORITIES)}"}
    due = None
    if due_date:
        try:
            due = date.fromisoformat(due_date.strip())
        except ValueError:
            return {"error": f"could not parse due_date {due_date!r}; use YYYY-MM-DD"}

    conn = db.get_conn()
    with conn:
        cur = conn.execute(
            "INSERT INTO todos (chat_id, text, due_date, priority) VALUES (?, ?, ?, ?)",
            (ctx.chat_id, text, due.isoformat() if due else None, priority),
        )
    return {
        "id": cur.lastrowid,
        "text": text,
        "due": timeutil.format_date(due) if due else None,
        "priority": priority,
    }
