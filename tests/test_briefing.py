"""Tests for the scheduled morning briefing and its commands (Telegram mocked)."""

import asyncio
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot import config, db, history, settings
from bot.agent import AgentResult
from bot.jobs import briefing

NOW = datetime(2026, 11, 14, 7, 30, tzinfo=timezone.utc)  # Sat 14 Nov, 07:30 London


@pytest.fixture(autouse=True)
def setup(london, freeze, monkeypatch):
    freeze(NOW)
    monkeypatch.setattr(config, "ALLOWED_USER_IDS", {1})


def _user_message_at(dt: datetime, text="hi"):
    history.add_exchange(1, text, "reply")
    conn = db.get_conn()
    with conn:
        conn.execute("UPDATE messages SET created_at = ? WHERE chat_id = 1",
                     (dt.strftime("%Y-%m-%dT%H:%M:%SZ"),))


@pytest.fixture
def agent_calls(monkeypatch):
    calls = []

    async def fake_run_agent(chat_id, content, history_text=None, model=None, trigger="text"):
        calls.append({"chat_id": chat_id, "content": content, "history_text": history_text, "model": model})
        history.add_exchange(chat_id, history_text, "☀️ Sunny, 2 to-dos, 3 headlines")
        return AgentResult(text="☀️ **Sunny**, 2 to-dos, 3 headlines")

    monkeypatch.setattr(briefing, "run_agent", fake_run_agent)
    return calls


# --- deciding whether to send ------------------------------------------------

def test_sends_when_quiet_and_not_yet_sent():
    assert briefing.skip_reason(1) is None


def test_skips_if_already_sent_today():
    settings.set(1, "last_briefing_date", "2026-11-14")
    assert briefing.skip_reason(1) == "already sent today"
    settings.set(1, "last_briefing_date", "2026-11-13")
    assert briefing.skip_reason(1) is None


def test_skips_if_user_chatted_recently():
    _user_message_at(NOW - timedelta(minutes=10))
    assert "last 30 minutes" in briefing.skip_reason(1)


def test_old_chat_does_not_block():
    _user_message_at(NOW - timedelta(minutes=45))
    assert briefing.skip_reason(1) is None


def test_the_briefings_own_history_entry_does_not_count():
    _user_message_at(NOW - timedelta(minutes=5), text=briefing.HISTORY_TEXT)
    assert briefing.skip_reason(1) is None


# --- running it ------------------------------------------------------------

def test_run_briefing_uses_fast_model_marks_date_and_sends(agent_calls):
    bot = SimpleNamespace(send_message=AsyncMock())
    settings.set(1, "topics", ["tech", "science"])
    asyncio.run(briefing.run_briefing(bot, 1))

    (call,) = agent_calls
    assert call["model"] == config.FAST_MODEL
    assert call["history_text"] == "[scheduled: morning briefing]"
    assert "3 headlines on my topics (tech, science)" in call["content"]
    assert "Under 12 lines" in call["content"] and "don't ask me any questions" in call["content"]
    assert settings.get(1, "last_briefing_date") == "2026-11-14"
    args, kwargs = bot.send_message.await_args
    assert args == (1, "☀️ <b>Sunny</b>, 2 to-dos, 3 headlines") and kwargs == {"parse_mode": "HTML"}


def test_date_is_marked_even_if_generation_fails(monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("api down")
    monkeypatch.setattr(briefing, "run_agent", boom)
    with pytest.raises(RuntimeError):
        asyncio.run(briefing.run_briefing(SimpleNamespace(send_message=AsyncMock()), 1))
    assert settings.get(1, "last_briefing_date") == "2026-11-14"  # at most once per day


def test_job_skips_or_sends_and_never_twice(agent_calls):
    bot = SimpleNamespace(send_message=AsyncMock())
    context = SimpleNamespace(job=SimpleNamespace(chat_id=1), bot=bot)
    asyncio.run(briefing.briefing_job(context))
    asyncio.run(briefing.briefing_job(context))  # same day again
    assert len(agent_calls) == 1
    assert bot.send_message.await_count == 1


def test_job_survives_errors(monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("api down")
    monkeypatch.setattr(briefing, "run_agent", boom)
    context = SimpleNamespace(job=SimpleNamespace(chat_id=1), bot=SimpleNamespace(send_message=AsyncMock()))
    asyncio.run(briefing.briefing_job(context))  # logged, not raised


def test_unknown_topics_are_dropped(monkeypatch):
    settings.set(1, "topics", ["tech", "removed-topic"])
    assert briefing.topics(1) == ["tech"]


# --- scheduling ------------------------------------------------------------

def test_restore_schedules_default_time_in_local_timezone(job_queue):
    briefing.restore(job_queue)
    (job,) = job_queue.live()
    assert job.name == "briefing:1" and job.chat_id == 1
    assert job.when == time(7, 30, tzinfo=config.TIMEZONE)


def test_reschedule_replaces_old_job_and_off_removes_it(job_queue):
    briefing.restore(job_queue)
    settings.set(1, "briefing_time", "06:45")
    assert briefing.schedule(job_queue, 1) == "06:45"
    assert [j.when.strftime("%H:%M") for j in job_queue.live()] == ["06:45"]
    settings.set(1, "briefing_time", "off")
    assert briefing.schedule(job_queue, 1) == "off"
    assert job_queue.live() == []


@pytest.mark.parametrize("value,expected", [("7:30", time(7, 30)), ("23:59", time(23, 59)),
                                            ("24:00", None), ("7.30", None), ("seven", None)])
def test_parse_time(value, expected):
    assert briefing.parse_time(value) == expected


# --- commands --------------------------------------------------------------

def _update(user_id=1):
    update = MagicMock()
    update.effective_chat.id = 1
    update.effective_user.id = user_id
    update.message.reply_text = AsyncMock()
    return update


def _reply(update):
    return update.message.reply_text.await_args.args[0]


def test_briefing_time_command(job_queue):
    from bot.main import briefing_time
    context = MagicMock(args=["6:05"])
    context.application.job_queue = job_queue
    update = _update()
    asyncio.run(briefing_time(update, context))
    assert "06:05" in _reply(update)
    assert settings.get(1, "briefing_time") == "06:05"
    assert [j.when.strftime("%H:%M") for j in job_queue.live()] == ["06:05"]

    context.args = ["off"]
    asyncio.run(briefing_time(update, context))
    assert "turned off" in _reply(update) and job_queue.live() == []

    context.args = ["25:00"]
    asyncio.run(briefing_time(update, context))
    assert "HH:MM" in _reply(update)


def test_topics_command(monkeypatch):
    from bot.main import topics
    update = _update()
    asyncio.run(topics(update, MagicMock(args=[])))
    assert "Your topics: world, tech" in _reply(update)
    asyncio.run(topics(update, MagicMock(args=["add", "Science"])))
    assert _reply(update) == "📰 Topics: world, tech, science"
    asyncio.run(topics(update, MagicMock(args=["remove", "world"])))
    assert settings.get(1, "topics") == ["tech", "science"]
    asyncio.run(topics(update, MagicMock(args=["add", "gardening"])))
    assert "don't have feeds" in _reply(update)
    asyncio.run(topics(update, MagicMock(args=["delete", "tech"])))
    assert "Usage" in _reply(update)


def test_briefing_now_ignores_the_daily_limit(agent_calls, monkeypatch):
    from bot import main
    monkeypatch.setattr(main, "keep_typing", AsyncMock())
    settings.set(1, "last_briefing_date", "2026-11-14")
    context = MagicMock()
    context.bot.send_message = AsyncMock()
    asyncio.run(main.briefing_now(_update(), context))
    assert len(agent_calls) == 1
    context.bot.send_message.assert_awaited()


def test_commands_ignore_strangers(agent_calls):
    from bot.main import briefing_now, topics
    update = _update(user_id=999)
    asyncio.run(topics(update, MagicMock(args=[])))
    asyncio.run(briefing_now(update, MagicMock()))
    update.message.reply_text.assert_not_awaited()
    assert agent_calls == []
