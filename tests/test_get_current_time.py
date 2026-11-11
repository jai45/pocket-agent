"""Tests for get_current_time (time is frozen, no real clock)."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from bot import config
from bot.tools import get_current_time as mod


def test_converts_utc_to_configured_timezone(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", ZoneInfo("Asia/Kolkata"))
    monkeypatch.setattr(mod, "_now_utc", lambda: datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc))
    result = mod.get_current_time()
    assert result == {
        "date": "2026-10-13",
        "time": "01:30",
        "weekday": "Tuesday",
        "timezone": "Asia/Kolkata",
        "utc_offset": "+0530",
    }
