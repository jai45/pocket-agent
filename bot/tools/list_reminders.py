"""List the chat's upcoming reminders."""

from bot import db, timeutil
from bot.tool_context import ToolContext

SPEC = {
    "name": "list_reminders",
    "description": (
        "List the user's upcoming reminders with their ids and next times. Use when "
        "the user asks what reminders they have, or before cancelling one when you "
        "don't know its id. Not for to-dos (use list_todos)."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


def list_reminders(ctx: ToolContext) -> dict:
    """Active reminders plus fired ones that are snoozed, soonest first."""
    rows = db.get_conn().execute(
        "SELECT * FROM reminders WHERE chat_id = ? AND "
        "(status = 'active' OR (status = 'fired' AND snooze_at IS NOT NULL))",
        (ctx.chat_id,),
    ).fetchall()
    items = []
    for row in rows:
        nxt = row["snooze_at"] if row["status"] == "fired" else row["fire_at"]
        item = {"id": row["id"], "text": row["text"], "next": timeutil.from_iso(nxt), "repeat": row["repeat"]}
        if row["snooze_at"]:
            item["snoozed_until"] = timeutil.format_local(timeutil.from_iso(row["snooze_at"]))
        items.append(item)
    items.sort(key=lambda i: i["next"])
    for item in items:
        item["next"] = timeutil.format_local(item["next"])
    return {"reminders": items} if items else {"reminders": [], "note": "no upcoming reminders"}
