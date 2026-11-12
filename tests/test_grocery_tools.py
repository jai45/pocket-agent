"""Tests for the grocery list tools."""

from bot.tool_context import ToolContext
from bot.tools.add_grocery_items import add_grocery_items
from bot.tools.clear_grocery_items import clear_grocery_items
from bot.tools.get_grocery_list import get_grocery_list

CTX = ToolContext(chat_id=1)


def test_duplicates_merge_into_quantity():
    add_grocery_items([{"name": "Milk"}, {"name": "egg", "quantity": 6}], CTX)
    result = add_grocery_items([{"name": " milk "}, {"name": "MILK"}], CTX)
    assert result["added"] == [{"name": "milk", "quantity": 3}]
    assert get_grocery_list(CTX)["items"] == [{"name": "milk", "quantity": 3}, {"name": "egg", "quantity": 6}]


def test_plain_strings_are_accepted():
    add_grocery_items(["bread", "oat  milk"], CTX)
    assert [i["name"] for i in get_grocery_list(CTX)["items"]] == ["bread", "oat milk"]


def test_add_validation():
    assert "error" in add_grocery_items([], CTX)
    assert "error" in add_grocery_items([{"name": "  "}], CTX)
    assert "error" in add_grocery_items([{"name": "x", "quantity": 0}], CTX)


def test_clear_some_reports_missing():
    add_grocery_items(["milk", "bread"], CTX)
    assert clear_grocery_items(CTX, items=["Milk", "cheese"]) == {"removed": ["milk"], "not_on_list": ["cheese"]}
    assert get_grocery_list(CTX)["items"] == [{"name": "bread", "quantity": 1}]


def test_clear_all_and_empty_list():
    add_grocery_items(["milk", "bread"], CTX)
    assert clear_grocery_items(CTX, all=True) == {"cleared": "all", "removed_count": 2}
    assert get_grocery_list(CTX) == {"items": [], "note": "the grocery list is empty"}
    assert "error" in clear_grocery_items(CTX)


def test_lists_are_per_chat():
    add_grocery_items(["milk"], CTX)
    other = ToolContext(chat_id=2)
    assert get_grocery_list(other)["items"] == []
    assert clear_grocery_items(other, all=True)["removed_count"] == 0
    assert len(get_grocery_list(CTX)["items"]) == 1
