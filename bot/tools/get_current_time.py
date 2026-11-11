"""Current date and time in the user's timezone.

The model has no clock, and its sense of "today" comes from training data,
so any question involving now, today or this week needs this tool.
"""

from datetime import datetime, timezone

from bot import config

SPEC = {
    "name": "get_current_time",
    "description": (
        "Get the current date, time and weekday in the user's timezone. Use this "
        "whenever the answer depends on the current date or time (today, tomorrow, "
        "this week, how long until...). Never guess the date. Not needed for "
        "questions that don't involve the present moment."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


def _now_utc() -> datetime:
    """Separate function so tests can freeze time."""
    return datetime.now(timezone.utc)


def get_current_time() -> dict:
    """Return the local date, time, weekday and timezone name."""
    local = _now_utc().astimezone(config.TIMEZONE)
    return {
        "date": local.strftime("%Y-%m-%d"),
        "time": local.strftime("%H:%M"),
        "weekday": local.strftime("%A"),
        "timezone": str(config.TIMEZONE),
        "utc_offset": local.strftime("%z"),
    }
