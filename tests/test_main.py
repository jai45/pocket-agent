"""Tests for the pure helpers in bot.main (no network, no Telegram)."""

from bot.agent import AgentResult, ToolCall
from bot.main import format_trace, split_message


def test_split_short_message_is_untouched():
    assert split_message("hello") == ["hello"]


def test_split_long_message_respects_limit_and_keeps_content():
    text = "\n".join(f"line {i}" for i in range(2000))
    chunks = split_message(text, limit=100)
    assert all(len(c) <= 100 for c in chunks)
    assert "\n".join(chunks) == text


def test_split_without_whitespace_hard_cuts():
    chunks = split_message("x" * 250, limit=100)
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_format_trace_lists_each_call():
    result = AgentResult("hi", [
        ToolCall(1, "calculate", {"expression": "2+2"}, '{"result": 4}', False),
        ToolCall(1, "fetch_url", {"url": "x"}, '{"error": "nope"}', True),
    ])
    trace = format_trace(result)
    assert "1. calculate(expression='2+2') →" in trace
    assert "⚠️" in trace.splitlines()[1]


def test_format_trace_without_tools():
    assert format_trace(AgentResult("hi")) == "🔧 no tools used"


def test_send_formatted_uses_html():
    import asyncio
    from unittest.mock import AsyncMock

    from bot.main import send_formatted

    message = AsyncMock()
    asyncio.run(send_formatted(message, "**hi**"))
    message.reply_text.assert_awaited_once_with("<b>hi</b>", parse_mode="HTML")


def test_send_formatted_falls_back_to_plain_text():
    import asyncio
    from unittest.mock import AsyncMock

    from telegram.error import BadRequest

    from bot.main import send_formatted

    message = AsyncMock()
    message.reply_text.side_effect = [BadRequest("can't parse entities"), None]
    asyncio.run(send_formatted(message, "**hi**"))
    assert message.reply_text.await_args_list[-1].args == ("**hi**",)
