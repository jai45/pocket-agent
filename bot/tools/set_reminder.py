"""Create a reminder that the bot will send at a given time."""

from bot import db, reminders, timeutil
from bot.tool_context import ToolContext

REPEATS = ("none", "daily", "weekly")

SPEC = {
    "name": "set_reminder",
    "description": (
        "Schedule a reminder message to be sent to the user at a specific time, "
        "optionally repeating daily or weekly. Use when the user says 'remind me...'. "
        "ALWAYS call get_current_time first and convert phrases like 'tomorrow at 6' "
        "or 'in 2 hours' into an ISO 8601 datetime in the user's timezone. "
        "Do not use it for tasks without a specific time (use add_todo)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "What to remind the user about, e.g. 'call mum'."},
            "when_iso": {
                "type": "string",
                "description": "Local date and time, ISO 8601 without offset, e.g. '2026-11-13T18:00'.",
            },
            "repeat": {"type": "string", "enum": list(REPEATS), "description": "Default 'none'."},
        },
        "required": ["text", "when_iso"],
    },
}


def set_reminder(text: str, when_iso: str, ctx: ToolContext, repeat: str = "none") -> dict:
    """Validate, save in UTC, schedule, and return the resolved local time."""
    text = text.strip()
    if not text:
        return {"error": "reminder text is empty"}
    if repeat not in REPEATS:
        return {"error": f"repeat must be one of {', '.join(REPEATS)}"}
    try:
        when = timeutil.parse_user_datetime(when_iso)
    except ValueError:
        return {"error": f"could not parse {when_iso!r}; use ISO 8601 like 2026-11-13T18:00"}
    now = timeutil.utc_now()
    if when <= now:
        # Usually Claude resolved the date wrong; tell it what "now" is.
        return {"error": f"that time is in the past (it is now {timeutil.format_local(now)})"}

    conn = db.get_conn()
    with conn:
        cur = conn.execute(
            "INSERT INTO reminders (chat_id, text, fire_at, repeat) VALUES (?, ?, ?, ?)",
            (ctx.chat_id, text, timeutil.to_iso(when), repeat),
        )
    reminders.schedule(reminders.get(cur.lastrowid, ctx.chat_id))
    return {"id": cur.lastrowid, "text": text, "when": timeutil.format_local(when), "repeat": repeat}
