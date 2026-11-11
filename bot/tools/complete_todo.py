"""Mark one of the chat's to-dos as done."""

from bot import db, timeutil
from bot.tool_context import ToolContext

SPEC = {
    "name": "complete_todo",
    "description": (
        "Mark a to-do as done by its id. If you don't know the id, call list_todos "
        "first. Do not guess ids."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "To-do id from list_todos."}},
        "required": ["id"],
    },
}


def complete_todo(id: int, ctx: ToolContext) -> dict:  # noqa: A002 - matches the tool schema
    """Set done_at (UTC). Completed items stay in the table as history."""
    row = db.get_conn().execute(
        "SELECT * FROM todos WHERE id = ? AND chat_id = ?", (id, ctx.chat_id)
    ).fetchone()
    if row is None:
        return {"error": f"no to-do with id {id}"}
    if row["done_at"]:
        return {"error": f"to-do {id} is already done"}
    conn = db.get_conn()
    with conn:
        conn.execute("UPDATE todos SET done_at = ? WHERE id = ?", (timeutil.to_iso(timeutil.utc_now()), id))
    return {"completed": id, "text": row["text"]}
