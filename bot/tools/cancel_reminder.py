"""Cancel one of the chat's reminders."""

from bot import db, reminders
from bot.tool_context import ToolContext

SPEC = {
    "name": "cancel_reminder",
    "description": (
        "Cancel a reminder by its id (stops all future repeats too). If you don't "
        "know the id, call list_reminders first. Do not guess ids."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "Reminder id from list_reminders."}},
        "required": ["id"],
    },
}


def cancel_reminder(id: int, ctx: ToolContext) -> dict:  # noqa: A002 - matches the tool schema
    """Mark cancelled and remove its scheduled jobs."""
    row = reminders.get(id, ctx.chat_id)
    if row is None or row["status"] in ("done", "cancelled"):
        return {"error": f"no active reminder with id {id}"}
    conn = db.get_conn()
    with conn:
        conn.execute("UPDATE reminders SET status = 'cancelled', snooze_at = NULL WHERE id = ?", (id,))
    reminders.unschedule(id)
    return {"cancelled": id, "text": row["text"]}
