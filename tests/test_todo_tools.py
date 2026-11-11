"""Tests for add_todo, list_todos and complete_todo."""

from datetime import datetime, timezone

import pytest

from bot.tool_context import ToolContext
from bot.tools.add_todo import add_todo
from bot.tools.complete_todo import complete_todo
from bot.tools.list_todos import list_todos

CTX = ToolContext(chat_id=1)


@pytest.fixture(autouse=True)
def setup(london, freeze):
    freeze(datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc))  # Thu 12 Nov


def test_add_returns_resolved_date():
    assert add_todo("renew passport", CTX, due_date="2026-11-14", priority="high") == {
        "id": 1, "text": "renew passport", "due": "Sat 14 Nov", "priority": "high"}


def test_add_without_date_defaults_to_med():
    result = add_todo("read book", CTX)
    assert result["due"] is None and result["priority"] == "med"


def test_add_validation():
    assert "error" in add_todo("", CTX)
    assert "error" in add_todo("x", CTX, priority="urgent")
    assert "error" in add_todo("x", CTX, due_date="next friday")


def test_filters_and_sorting():
    add_todo("overdue low", CTX, due_date="2026-11-10", priority="low")
    add_todo("today med", CTX, due_date="2026-11-12")
    add_todo("future high", CTX, due_date="2026-11-20", priority="high")
    add_todo("undated high", CTX, priority="high")
    texts = lambda f: [t["text"] for t in list_todos(CTX, filter=f)["todos"]]  # noqa: E731
    assert texts("all") == ["future high", "undated high", "today med", "overdue low"]
    assert texts("today") == ["today med", "overdue low"]
    assert texts("overdue") == ["overdue low"]


def test_today_uses_local_date_not_utc(monkeypatch, freeze):
    from zoneinfo import ZoneInfo

    from bot import config
    # 23:30 UTC on the 12th is already the 13th in Kolkata.
    monkeypatch.setattr(config, "TIMEZONE", ZoneInfo("Asia/Kolkata"))
    freeze(datetime(2026, 11, 12, 23, 30, tzinfo=timezone.utc))
    add_todo("due 13th", CTX, due_date="2026-11-13")
    assert [t["text"] for t in list_todos(CTX, filter="today")["todos"]] == ["due 13th"]


def test_complete_hides_item_and_rejects_repeat():
    tid = add_todo("milk", CTX)["id"]
    assert complete_todo(tid, CTX) == {"completed": tid, "text": "milk"}
    assert list_todos(CTX)["todos"] == []
    assert "already done" in complete_todo(tid, CTX)["error"]


def test_todos_are_per_chat():
    tid = add_todo("mine", CTX)["id"]
    other = ToolContext(chat_id=2)
    assert list_todos(other)["todos"] == []
    assert "error" in complete_todo(tid, other)


def test_bad_filter():
    assert "error" in list_todos(CTX, filter="someday")
