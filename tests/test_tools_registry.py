"""Tests for the tool registry and dispatcher."""

import asyncio
import json

from bot import tools


def test_every_spec_has_a_matching_function():
    names = [s["name"] for s in tools.TOOL_SPECS]
    assert names == [
        "calculate", "convert_units", "fetch_url", "get_current_time",
        "set_reminder", "list_reminders", "cancel_reminder",
        "add_todo", "list_todos", "complete_todo",
        "add_expense", "expense_summary", "delete_expense",
        "add_grocery_items", "get_grocery_list", "clear_grocery_items",
        "save_note", "search_notes", "update_note", "delete_note",
        "remember_fact", "recall_facts", "forget_fact",
    ]
    for spec in tools.TOOL_SPECS:
        assert spec["description"] and spec["input_schema"]["type"] == "object"


def test_run_tool_returns_json_text():
    out = asyncio.run(tools.run_tool("calculate", {"expression": "6*7"}))
    assert json.loads(out)["result"] == 42


def test_unknown_tool_is_an_error_not_an_exception():
    out = asyncio.run(tools.run_tool("teleport", {}))
    assert tools.is_error(out)


def test_bad_arguments_are_an_error():
    out = asyncio.run(tools.run_tool("calculate", {"wrong": "1"}))
    assert "Bad input" in json.loads(out)["error"]


def test_exception_inside_tool_is_caught(monkeypatch):
    def boom(expression):
        raise RuntimeError("kaboom")
    monkeypatch.setitem(tools._FUNCTIONS, "calculate", boom)
    out = asyncio.run(tools.run_tool("calculate", {"expression": "1"}))
    assert json.loads(out) == {"error": "calculate failed: kaboom"}


def test_ctx_is_passed_only_to_tools_that_want_it():
    from bot.tool_context import ToolContext
    out = asyncio.run(tools.run_tool("add_todo", {"text": "milk"}, ToolContext(chat_id=5)))
    assert json.loads(out)["id"] >= 1
    # Tools without ctx still work when a ctx is supplied.
    out = asyncio.run(tools.run_tool("calculate", {"expression": "1+1"}, ToolContext(chat_id=5)))
    assert json.loads(out)["result"] == 2


def test_ctx_tool_without_ctx_is_an_error():
    out = asyncio.run(tools.run_tool("add_todo", {"text": "milk"}))
    assert tools.is_error(out)


def test_model_cannot_inject_ctx():
    from bot.tool_context import ToolContext
    sneaky = {"text": "x", "ctx": {"chat_id": 999}}
    asyncio.run(tools.run_tool("add_todo", sneaky, ToolContext(chat_id=5)))
    out = asyncio.run(tools.run_tool("list_todos", {}, ToolContext(chat_id=999)))
    assert json.loads(out)["todos"] == []
