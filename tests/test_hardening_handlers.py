"""Budget gate, /cost, overload message and the Yes/No buttons in bot.main."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot import config, llm, main, usage
from bot.agent import AgentResult


def _update(text="hi"):
    update = MagicMock()
    update.effective_chat.id = 1
    update.effective_user.id = 1
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def agent_spy(monkeypatch):
    calls = []

    async def fake_run_agent(chat_id, content, history_text=None, model=None, trigger="text"):
        calls.append({"model": model, "trigger": trigger})
        return AgentResult(text="ok")

    monkeypatch.setattr(config, "ALLOWED_USER_IDS", {1})
    monkeypatch.setattr(main, "run_agent", fake_run_agent)
    monkeypatch.setattr(main, "keep_typing", AsyncMock())
    monkeypatch.setattr(main, "send_formatted", AsyncMock())
    return calls


def replies(update):
    return [c.args[0] for c in update.message.reply_text.call_args_list]


def test_under_budget_uses_default_model(agent_spy, monkeypatch):
    monkeypatch.setattr(usage, "budget_state", lambda: usage.OK)
    asyncio.run(main.handle_text(_update(), MagicMock()))
    assert agent_spy == [{"model": None, "trigger": "text"}]


def test_over_budget_switches_to_fast_model_and_says_so_once(agent_spy, monkeypatch):
    monkeypatch.setattr(usage, "budget_state", lambda: usage.FAST)
    first, second = _update(), _update()
    asyncio.run(main.handle_text(first, MagicMock()))
    asyncio.run(main.handle_text(second, MagicMock()))
    assert [c["model"] for c in agent_spy] == [config.FAST_MODEL, config.FAST_MODEL]
    assert replies(first) == [main.BUDGET_FAST_TEXT]
    assert replies(second) == []


def test_twice_over_budget_refuses_without_calling_the_model(agent_spy, monkeypatch):
    monkeypatch.setattr(usage, "budget_state", lambda: usage.BLOCKED)
    update = _update()
    asyncio.run(main.handle_text(update, MagicMock()))
    assert agent_spy == []
    assert replies(update) == [main.BUDGET_BLOCKED_TEXT]


def test_overloaded_gives_friendly_message(monkeypatch):
    async def overloaded(*args, **kwargs):
        raise llm.ModelUnavailable("529")

    monkeypatch.setattr(config, "ALLOWED_USER_IDS", {1})
    monkeypatch.setattr(main, "run_agent", overloaded)
    monkeypatch.setattr(main, "keep_typing", AsyncMock())
    update = _update()
    asyncio.run(main.handle_text(update, MagicMock()))
    assert replies(update) == [main.OVERLOADED_TEXT]


def test_cost_command(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USER_IDS", {1})
    update = _update()
    asyncio.run(main.cost(update, MagicMock()))
    assert replies(update)[0].startswith("💰 Estimated API spend")


def test_pending_actions_get_yes_no_buttons(monkeypatch):
    from bot import confirmations
    action_id = confirmations.create(1, "forget_fact", {"id": 3}, 'forget fact #3 "x"')
    update = _update()
    asyncio.run(main.send_confirmations(update, AgentResult(text="ok", pending=[action_id])))
    call = update.message.reply_text.call_args
    assert call.args[0] == '❓ Okay to forget fact #3 "x"?'
    buttons = call.kwargs["reply_markup"].inline_keyboard[0]
    assert [b.callback_data for b in buttons] == [f"confirm:yes:{action_id}", f"confirm:no:{action_id}"]


def test_yes_button_resolves_and_replaces_the_question(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USER_IDS", {1})
    resolve = AsyncMock(return_value="✅ Done: x.")
    monkeypatch.setattr(main.confirmations, "resolve", resolve)
    query = SimpleNamespace(data="confirm:yes:7", message=SimpleNamespace(chat=SimpleNamespace(id=1)),
                            answer=AsyncMock(), edit_message_text=AsyncMock())
    update = MagicMock(callback_query=query)
    update.effective_user.id = 1
    asyncio.run(main.on_confirm(update, MagicMock()))
    resolve.assert_awaited_once_with(7, 1, approved=True)
    query.edit_message_text.assert_awaited_once_with("✅ Done: x.")


def test_strangers_cannot_press_yes(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USER_IDS", {1})
    resolve = AsyncMock()
    monkeypatch.setattr(main.confirmations, "resolve", resolve)
    query = SimpleNamespace(data="confirm:yes:7", answer=AsyncMock())
    update = MagicMock(callback_query=query)
    update.effective_user.id = 999
    asyncio.run(main.on_confirm(update, MagicMock()))
    resolve.assert_not_awaited()


def test_briefing_skipped_when_blocked(monkeypatch):
    from bot.jobs import briefing
    monkeypatch.setattr(usage, "budget_state", lambda: usage.BLOCKED)
    assert briefing.skip_reason(1) == "over 2x the daily budget"
