"""Tests for add_expense, expense_summary and delete_expense."""

from datetime import datetime, timezone

import pytest

from bot.tool_context import ToolContext
from bot.tools.add_expense import add_expense
from bot.tools.delete_expense import delete_expense
from bot.tools.expense_summary import expense_summary

CTX = ToolContext(chat_id=1)


@pytest.fixture(autouse=True)
def setup(london, freeze):
    freeze(datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc))  # Thu 12 Nov


def test_add_defaults_to_today_and_formats_money():
    assert add_expense(12.5, "food", "lunch", CTX) == {
        "id": 1, "amount": "$12.50", "category": "food", "note": "lunch", "date": "Thu 12 Nov"}


def test_add_validation():
    assert "error" in add_expense(0, "food", "x", CTX)
    assert "error" in add_expense(-3, "food", "x", CTX)
    assert "error" in add_expense(5, "groceries", "x", CTX)
    assert "error" in add_expense(5, "food", "x", CTX, date="yesterday")
    assert "future" in add_expense(5, "food", "x", CTX, date="2026-11-13")["error"]


def test_cents_add_up_exactly():
    for _ in range(3):
        add_expense(0.1, "food", "gum", CTX)
    assert expense_summary(CTX)["total"] == "$0.30"


def test_week_month_and_grouping():
    add_expense(20, "food", "groceries", CTX, date="2026-11-09")  # Mon, this week
    add_expense(45, "bills", "phone", CTX, date="2026-11-12")
    add_expense(5, "food", "coffee", CTX, date="2026-11-12")
    add_expense(100, "fun", "concert", CTX, date="2026-11-02")  # last week, this month
    add_expense(999, "shopping", "old", CTX, date="2026-10-30")  # last month

    week = expense_summary(CTX, period="week")
    assert week["period"] == "Mon 09 Nov – Thu 12 Nov"
    assert week["total"] == "$70.00" and week["count"] == 3
    assert week["by_category"] == [
        {"category": "bills", "total": "$45.00", "count": 1},
        {"category": "food", "total": "$25.00", "count": 2},
    ]
    assert [i["note"] for i in week["top_items"]] == ["phone", "groceries", "coffee"]

    month = expense_summary(CTX, period="month", group_by="day")
    assert month["total"] == "$170.00"
    assert month["by_day"] == [
        {"date": "Mon 02 Nov", "total": "$100.00"},
        {"date": "Mon 09 Nov", "total": "$20.00"},
        {"date": "Thu 12 Nov", "total": "$50.00"},
    ]


def test_custom_period_and_errors():
    add_expense(999, "shopping", "old", CTX, date="2026-10-30")
    assert expense_summary(CTX, period="custom", start_date="2026-10-01", end_date="2026-10-31")["total"] == "$999.00"
    assert "error" in expense_summary(CTX, period="custom")
    assert "error" in expense_summary(CTX, period="custom", start_date="2026-11-02", end_date="2026-11-01")
    assert "error" in expense_summary(CTX, period="year")
    assert "error" in expense_summary(CTX, group_by="week")


def test_empty_period():
    result = expense_summary(CTX, period="week")
    assert result["total"] == "$0.00" and result["note"] == "no expenses in this period"


def test_include_items_lists_ids_for_delete():
    add_expense(5, "food", "coffee", CTX)
    eid = add_expense(50, "food", "typo", CTX)["id"]
    items = expense_summary(CTX, include_items=True)["items"]
    assert [i["note"] for i in items] == ["typo", "coffee"]
    assert delete_expense(eid, CTX) == {"deleted": eid, "amount": "$50.00", "note": "typo"}
    assert expense_summary(CTX)["total"] == "$5.00"
    assert "error" in delete_expense(eid, CTX)


def test_expenses_are_per_chat():
    eid = add_expense(5, "food", "mine", CTX)["id"]
    other = ToolContext(chat_id=2)
    assert expense_summary(other)["count"] == 0
    assert "error" in delete_expense(eid, other)


def test_currency_symbol_from_config(monkeypatch):
    from bot import config
    monkeypatch.setattr(config, "CURRENCY", "₹")
    assert add_expense(1234.5, "bills", "rent", CTX)["amount"] == "₹1,234.50"
