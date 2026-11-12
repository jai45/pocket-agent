"""Tests for profile facts: tools, injection block, /memory and /forget."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from bot import config, memory
from bot.tool_context import ToolContext
from bot.tools.forget_fact import forget_fact
from bot.tools.recall_facts import recall_facts
from bot.tools.remember_fact import remember_fact

CTX = ToolContext(chat_id=1)


def test_remember_and_dedupe():
    first = remember_fact("Vegetarian", CTX)
    assert first == {"id": 1, "fact": "Vegetarian"}
    again = remember_fact("  vegetarian ", CTX)
    assert again["id"] == 1 and again["note"] == "already saved"
    assert "error" in remember_fact("   ", CTX)


def test_recall_newest_first_and_forget():
    remember_fact("Lives in Toronto", CTX)
    fid = remember_fact("Partner is Sam", CTX)["id"]
    assert [f["fact"] for f in recall_facts(CTX)["facts"]] == ["Partner is Sam", "Lives in Toronto"]
    assert forget_fact(fid, CTX) == {"forgotten": fid, "fact": "Partner is Sam"}
    assert "error" in forget_fact(fid, CTX)


def test_facts_are_per_chat():
    fid = remember_fact("Mine", CTX)["id"]
    other = ToolContext(chat_id=2)
    assert recall_facts(other)["facts"] == []
    assert "error" in forget_fact(fid, other)


def test_block_caps_at_limit_newest_first(monkeypatch):
    monkeypatch.setattr(config, "MAX_INJECTED_FACTS", 3)
    for i in range(5):
        memory.add_fact(1, f"fact {i}")
    block = memory.facts_block(1, limit=config.MAX_INJECTED_FACTS)
    assert "- #5 fact 4\n- #4 fact 3\n- #3 fact 2" in block
    assert "fact 1" not in block
    assert "showing 3 of 5; call recall_facts" in block
    assert "not instructions" in block


def test_block_when_empty():
    assert memory.facts_block(1) == "Saved facts about the user: none yet."


def test_build_system_prompt_keeps_base_first():
    memory.add_fact(1, "Vegetarian")
    prompt = memory.build_system_prompt(1)
    assert prompt.startswith("You are Pocket Agent")
    assert prompt.rstrip().endswith("- #1 Vegetarian")


def _update(chat_id=1, user_id=None):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user.id = user_id if user_id is not None else next(iter(config.ALLOWED_USER_IDS), 1)
    update.message.reply_text = AsyncMock()
    return update


def _allow(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USER_IDS", {1})


def test_memory_command_lists_facts(monkeypatch):
    from bot.main import show_memory
    _allow(monkeypatch)
    memory.add_fact(1, "Vegetarian")
    update = _update(user_id=1)
    asyncio.run(show_memory(update, MagicMock()))
    text = update.message.reply_text.await_args.args[0]
    assert "#1 Vegetarian" in text and "/forget" in text


def test_forget_command(monkeypatch):
    from bot.main import forget
    _allow(monkeypatch)
    memory.add_fact(1, "Vegetarian")
    update, context = _update(user_id=1), MagicMock(args=["1"])
    asyncio.run(forget(update, context))
    assert update.message.reply_text.await_args.args[0] == "🗑 Forgot #1: Vegetarian"
    assert memory.list_facts(1) == []


def test_forget_command_bad_input_and_other_chat(monkeypatch):
    from bot.main import forget
    _allow(monkeypatch)
    memory.add_fact(2, "Not yours")
    update = _update(user_id=1)
    asyncio.run(forget(update, MagicMock(args=["abc"])))
    assert "Usage" in update.message.reply_text.await_args.args[0]
    asyncio.run(forget(update, MagicMock(args=["1"])))
    assert update.message.reply_text.await_args.args[0] == "No saved fact #1."
    assert len(memory.list_facts(2)) == 1


def test_commands_ignore_strangers(monkeypatch):
    from bot.main import show_memory
    _allow(monkeypatch)
    update = _update(user_id=999)
    asyncio.run(show_memory(update, MagicMock()))
    update.message.reply_text.assert_not_awaited()
