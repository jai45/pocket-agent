"""Tests for set_reminder, list_reminders and cancel_reminder."""

from datetime import datetime, timezone

import pytest

from bot.tool_context import ToolContext
from bot.tools.cancel_reminder import cancel_reminder
from bot.tools.list_reminders import list_reminders
from bot.tools.set_reminder import set_reminder

CTX = ToolContext(chat_id=1)
OTHER = ToolContext(chat_id=2)
# Wed 12 Nov 2026, 10:00 in London (GMT = UTC in November).
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def setup(london, freeze):
    freeze(NOW)


def test_local_time_is_stored_as_utc_and_shown_local(monkeypatch, job_queue):
    from zoneinfo import ZoneInfo

    from bot import config, db
    monkeypatch.setattr(config, "TIMEZONE", ZoneInfo("Asia/Kolkata"))  # UTC+5:30
    result = set_reminder("call mum", "2026-11-12T18:00", CTX)
    assert result["when"] == "Thu 12 Nov 18:00"
    stored = db.get_conn().execute("SELECT fire_at FROM reminders").fetchone()[0]
    assert stored == "2026-11-12T12:30:00+00:00"
    assert job_queue.live()[0].when == datetime(2026, 11, 12, 12, 30, tzinfo=timezone.utc)


def test_explicit_offset_is_respected():
    result = set_reminder("x", "2026-11-12T18:00+01:00", CTX)
    assert result["when"] == "Thu 12 Nov 17:00"  # 18:00 CET == 17:00 London


def test_past_time_is_refused_with_current_time():
    result = set_reminder("x", "2026-11-12T09:00", CTX)
    assert "past" in result["error"] and "Thu 12 Nov 10:00" in result["error"]


def test_bad_inputs():
    assert "error" in set_reminder("x", "tomorrow at 6", CTX)
    assert "error" in set_reminder("x", "2026-11-13T18:00", CTX, repeat="hourly")
    assert "error" in set_reminder("  ", "2026-11-13T18:00", CTX)


def test_list_is_per_chat_and_sorted():
    set_reminder("later", "2026-11-14T09:00", CTX, repeat="weekly")
    set_reminder("sooner", "2026-11-13T09:00", CTX)
    set_reminder("not mine", "2026-11-13T08:00", OTHER)
    items = list_reminders(CTX)["reminders"]
    assert [i["text"] for i in items] == ["sooner", "later"]
    assert items[1] == {"id": items[1]["id"], "text": "later", "next": "Sat 14 Nov 09:00", "repeat": "weekly"}


def test_empty_list():
    assert list_reminders(CTX) == {"reminders": [], "note": "no upcoming reminders"}


def test_cancel_removes_job_and_hides_from_list(job_queue):
    rid = set_reminder("x", "2026-11-13T09:00", CTX)["id"]
    assert cancel_reminder(rid, CTX) == {"cancelled": rid, "text": "x"}
    assert job_queue.live() == []
    assert list_reminders(CTX)["reminders"] == []
    assert "error" in cancel_reminder(rid, CTX)  # already cancelled


def test_cannot_cancel_another_chats_reminder():
    rid = set_reminder("x", "2026-11-13T09:00", OTHER)["id"]
    assert "error" in cancel_reminder(rid, CTX)
