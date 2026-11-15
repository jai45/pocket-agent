"""Confirmation guardrail: risky tools are parked, and only a Yes tap runs them."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from bot import confirmations, history, memory, reminders
from bot.tool_context import ToolContext
from bot.tools import add_grocery_items as agi
from bot.tools import confirmation_id, needs_confirmation, run_tool
from bot.tools import set_reminder as sr

CTX = ToolContext(chat_id=1)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def reminder_id(job_queue):
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    return sr.set_reminder("call mum", when, CTX)["id"]


def test_flags():
    assert needs_confirmation("cancel_reminder", {"id": 1})
    assert needs_confirmation("forget_fact", {"id": 1})
    assert needs_confirmation("clear_grocery_items", {"all": True})
    assert not needs_confirmation("clear_grocery_items", {"items": ["eggs"]})
    assert not needs_confirmation("add_todo", {"text": "x"})


def test_cancel_is_requested_not_executed(reminder_id):
    result = run(run_tool("cancel_reminder", {"id": reminder_id}, CTX))
    action_id = confirmation_id(result)
    assert action_id is not None
    assert json.loads(result)["action"] == f'cancel reminder #{reminder_id} "call mum"'
    assert reminders.get(reminder_id, 1)["status"] == "active"
    assert confirmations.question(action_id, 1) == f'❓ Okay to cancel reminder #{reminder_id} "call mum"?'


def test_yes_runs_the_tool_and_records_history(reminder_id):
    action_id = confirmation_id(run(run_tool("cancel_reminder", {"id": reminder_id}, CTX)))
    text = run(confirmations.resolve(action_id, 1, approved=True))
    assert text == f'✅ Done: cancel reminder #{reminder_id} "call mum".'
    assert reminders.get(reminder_id, 1)["status"] == "cancelled"
    stored = history.get_history(1)
    assert stored[0]["content"].startswith("[button: confirmed cancel_reminder")
    assert "cancel_reminder(id=" in stored[1]["content"]  # tool log, so the model sees evidence


def test_no_leaves_it_alone(reminder_id):
    action_id = confirmation_id(run(run_tool("cancel_reminder", {"id": reminder_id}, CTX)))
    assert run(confirmations.resolve(action_id, 1, approved=False)) == confirmations.DECLINED_TEXT
    assert reminders.get(reminder_id, 1)["status"] == "active"


def test_double_tap_runs_once(reminder_id):
    action_id = confirmation_id(run(run_tool("cancel_reminder", {"id": reminder_id}, CTX)))
    run(confirmations.resolve(action_id, 1, approved=True))
    assert run(confirmations.resolve(action_id, 1, approved=True)) == confirmations.GONE_TEXT


def test_other_chat_cannot_resolve(reminder_id):
    action_id = confirmation_id(run(run_tool("cancel_reminder", {"id": reminder_id}, CTX)))
    assert run(confirmations.resolve(action_id, 2, approved=True)) == confirmations.GONE_TEXT
    assert reminders.get(reminder_id, 1)["status"] == "active"


def test_expires_after_ten_minutes(reminder_id, freeze):
    action_id = confirmation_id(run(run_tool("cancel_reminder", {"id": reminder_id}, CTX)))
    freeze(datetime.now(timezone.utc) + timedelta(minutes=11))
    assert run(confirmations.resolve(action_id, 1, approved=True)) == confirmations.EXPIRED_TEXT
    assert reminders.get(reminder_id, 1)["status"] == "active"


def test_bad_id_fails_before_any_buttons():
    result = json.loads(run(run_tool("cancel_reminder", {"id": 99}, CTX)))
    assert result == {"error": "no active reminder with id 99"}
    assert run(run_tool("forget_fact", {"id": 99}, CTX)).startswith('{"error"')


def test_forget_fact_needs_yes():
    fact_id, _ = memory.add_fact(1, "Lives in Toronto")
    action_id = confirmation_id(run(run_tool("forget_fact", {"id": fact_id}, CTX)))
    assert memory.count_facts(1) == 1
    run(confirmations.resolve(action_id, 1, approved=True))
    assert memory.count_facts(1) == 0


def test_clearing_some_groceries_runs_at_once_but_all_waits():
    agi.add_grocery_items(["eggs", "milk", "bread"], CTX)
    assert "removed" in json.loads(run(run_tool("clear_grocery_items", {"items": ["eggs"]}, CTX)))
    result = json.loads(run(run_tool("clear_grocery_items", {"all": True}, CTX)))
    assert result["action"] == "clear the whole grocery list (2 items)"
    run(confirmations.resolve(result["confirmation_id"], 1, approved=True))
    assert json.loads(run(run_tool("get_grocery_list", {}, CTX)))["items"] == []


def test_clearing_an_empty_list_is_an_error_not_a_question():
    assert "already empty" in run(run_tool("clear_grocery_items", {"all": True}, CTX))


def test_model_cannot_pass_confirmed(reminder_id):
    """'confirmed' isn't a tool argument; sending it just becomes bad input."""
    result = run(run_tool("cancel_reminder", {"id": reminder_id, "confirmed": True}, CTX))
    assert reminders.get(reminder_id, 1)["status"] == "active"
    assert "error" in json.loads(result)
