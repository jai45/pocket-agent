"""Tests for the tool registry and dispatcher."""

import asyncio
import json

from bot import tools


def test_every_spec_has_a_matching_function():
    names = [s["name"] for s in tools.TOOL_SPECS]
    assert names == ["calculate", "convert_units", "fetch_url", "get_current_time"]
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
