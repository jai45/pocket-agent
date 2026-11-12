"""List the chat's reminders: upcoming ones, and optionally recent past ones."""

from bot import db, timeutil
from bot.tool_context import ToolContext

PAST_LIMIT = 10

SPEC = {
    "name": "list_reminders",
    "description": (
        "List the user's upcoming reminders with their ids and next times. Use when "
        "the user asks what reminders they have, or before cancelling one when you "
        "don't know its id. Use this, not conversation memory, whenever asked what "
        "reminders exist or were set. Set include_past=true when the question is "
        "about earlier reminders (e.g. 'what did I ask you to remind me about?'); it "
        "adds the most recent fired, done and cancelled ones. Not for to-dos (use "
        "list_todos)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "include_past": {
                "type": "boolean",
                "description": f"Also return the last {PAST_LIMIT} fired/done/cancelled reminders. Default false.",
            }
        },
    },
}

# Upcoming = will still send a message: active, or already fired but snoozed.
_UPCOMING = "(status = 'active' OR (status = 'fired' AND snooze_at IS NOT NULL))"


def _upcoming(chat_id: int) -> list[dict]:
    """Active reminders plus fired ones that are snoozed, soonest first."""
    rows = db.get_conn().execute(
        f"SELECT * FROM reminders WHERE chat_id = ? AND {_UPCOMING}", (chat_id,)
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
    return items


def _past(chat_id: int) -> list[dict]:
    """Most recently created reminders that won't send again, newest first.

    For a cancelled repeating reminder, `time` is the occurrence that was
    next when it was cancelled, which is what "scheduled for" means here.
    """
    rows = db.get_conn().execute(
        f"SELECT * FROM reminders WHERE chat_id = ? AND NOT {_UPCOMING} ORDER BY id DESC LIMIT ?",
        (chat_id, PAST_LIMIT),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "text": row["text"],
            "status": row["status"],
            "time": timeutil.format_local(timeutil.from_iso(row["fire_at"])),
            "repeat": row["repeat"],
        }
        for row in rows
    ]


def list_reminders(ctx: ToolContext, include_past: bool = False) -> dict:
    """Upcoming reminders, plus recent past ones when asked."""
    upcoming = _upcoming(ctx.chat_id)
    result: dict = {"reminders": upcoming} if upcoming else {"reminders": [], "note": "no upcoming reminders"}
    if include_past:
        result["past"] = _past(ctx.chat_id)
    return result
