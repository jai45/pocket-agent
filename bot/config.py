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

# Symbol shown before money amounts. Expenses assume a single currency.
CURRENCY: str = os.getenv("CURRENCY", "$")
# How many profile facts are injected into the system prompt each turn.
MAX_INJECTED_FACTS: int = 30

# Proactive morning briefing (Phase 5).
# Weather fallback when no location is given and none is known from facts.
HOME_CITY: str = os.getenv("HOME_CITY", "").strip()
# Default daily briefing time (HH:MM in TIMEZONE); each chat can change it.
BRIEFING_TIME: str = os.getenv("BRIEFING_TIME", "07:30").strip()
# Topic -> RSS/Atom feeds. Feed URLs live in code, not chat: /topics can only
# pick from these, so nobody can point the bot at an arbitrary URL.
NEWS_FEEDS: dict[str, list[str]] = {
    "world": [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://feeds.npr.org/1004/rss.xml",
    ],
    "tech": [
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://www.theverge.com/rss/index.xml",
        "https://hnrss.org/frontpage",
    ],
    "science": [
        "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        "https://www.sciencedaily.com/rss/top/science.xml",
    ],
    "business": [
        "https://feeds.bbci.co.uk/news/business/rss.xml",
        "https://feeds.npr.org/1006/rss.xml",
    ],
}
DEFAULT_TOPICS: list[str] = ["world", "tech"]

# SQLite file for history, reminders and to-dos (data/ is git-ignored).
DB_PATH: Path = Path(os.getenv("DB_PATH", "data/pocket.db"))

ALLOWED_USER_IDS: set[int] = _parse_user_ids(os.getenv("ALLOWED_USER_IDS", ""))
TIMEZONE: ZoneInfo = _load_timezone(os.getenv("TIMEZONE", "UTC").strip() or "UTC")
