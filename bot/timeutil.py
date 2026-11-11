"""Time helpers: store UTC, show local.

Everything saved to the database is UTC (unambiguous, sorts correctly,
survives DST changes and TIMEZONE edits). We convert to the user's
TIMEZONE only when reading their input or showing a time back to them.
"""

from datetime import date, datetime, timezone

from bot import config


def utc_now() -> datetime:
    """Current time in UTC. One function so tests can freeze the clock."""
    return datetime.now(timezone.utc)


def local_today() -> date:
    """Today's date on the user's clock (what "today" means to them)."""
    return utc_now().astimezone(config.TIMEZONE).date()


def to_iso(dt: datetime) -> str:
    """Aware datetime -> ISO 8601 UTC string for the database."""
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def from_iso(value: str) -> datetime:
    """ISO string from the database -> aware UTC datetime."""
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def parse_user_datetime(value: str) -> datetime:
    """Parse an ISO datetime from Claude; no offset means the user's TIMEZONE."""
    dt = datetime.fromisoformat(value.strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=config.TIMEZONE)
    return dt.astimezone(timezone.utc)


def format_local(dt: datetime) -> str:
    """Short human time in the user's TIMEZONE, e.g. 'Thu 13 Nov 18:00'."""
    return dt.astimezone(config.TIMEZONE).strftime("%a %d %b %H:%M")


def format_date(d: date) -> str:
    """Short human date, e.g. 'Fri 14 Nov'."""
    return d.strftime("%a %d %b")
