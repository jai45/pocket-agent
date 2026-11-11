"""Central configuration.

Everything secret or environment-specific comes from .env so the code can be
committed safely and the same code runs on a laptop or a server.
"""

import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    """Fail fast at startup if a required secret is missing.

    Crashing immediately with a clear message beats a confusing auth error
    on the first Telegram message. The value itself is never printed.
    """
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required setting {name} in .env")
    return value


def _parse_user_ids(raw: str) -> set[int]:
    """Turn '123, 456' into {123, 456}. Bad entries are a config error."""
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            ids.add(int(part))
    return ids


def _load_timezone(name: str) -> ZoneInfo:
    """Load the display timezone; a typo should fail loudly, not silently be UTC."""
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"Unknown TIMEZONE {name!r} in .env") from exc


TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY: str = _require("ANTHROPIC_API_KEY")

DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "claude-sonnet-5-5")
FAST_MODEL: str = os.getenv("FAST_MODEL", "claude-haiku-5-5")

MAX_TOKENS: int = 4096
# Sonnet 5.5 thinks by default at "high" effort; thinking tokens count toward
# MAX_TOKENS. "low" keeps chat replies fast and leaves room for the answer.
EFFORT: str = os.getenv("EFFORT", "low")
HISTORY_LIMIT: int = 20
# Hard stop for the agent loop so a confused model can't call tools forever.
MAX_AGENT_STEPS: int = 8

# SQLite file for history, reminders and to-dos (data/ is git-ignored).
DB_PATH: Path = Path(os.getenv("DB_PATH", "data/pocket.db"))

ALLOWED_USER_IDS: set[int] = _parse_user_ids(os.getenv("ALLOWED_USER_IDS", ""))
TIMEZONE: ZoneInfo = _load_timezone(os.getenv("TIMEZONE", "UTC").strip() or "UTC")
