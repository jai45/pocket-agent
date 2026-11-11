"""Tests for reminder scheduling, firing, buttons and startup restore."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import db, reminders, timeutil
from bot.tool_context import ToolContext
from bot.tools.set_reminder import set_reminder

CTX = ToolContext(chat_id=1)
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def setup(london, freeze):
    freeze(NOW)


def row(rid):
    return db.get_conn().execute("SELECT * FROM reminders WHERE id = ?", (rid,)).fetchone()


def fire(job):
    bot = AsyncMock()
    asyncio.run(job.callback(SimpleNamespace(job=job, bot=bot)))
    return bot


# --- next occurrence ----------------------------------------------------------

def test_daily_keeps_local_wall_clock_across_dst(london):
    # 08:00 London on Sat 28 Mar 2026 is 08:00 UTC; clocks go forward on the 29th.
    first = datetime(2026, 3, 28, 8, 0, tzinfo=timezone.utc)
    nxt = reminders.next_occurrence(first, "daily", after=first)
    assert nxt == datetime(2026, 3, 29, 7, 0, tzinfo=timezone.utc)  # 08:00 BST
    assert timeutil.format_local(nxt).endswith("08:00")


def test_next_occurrence_skips_missed_ones():
    first = NOW - timedelta(days=3, hours=1)
    assert reminders.next_occurrence(first, "daily", after=NOW) == NOW + timedelta(hours=23)


def test_weekly_step():
    assert reminders.next_occurrence(NOW, "weekly", after=NOW) == NOW + timedelta(weeks=1)


# --- firing -----------------------------------------------------------------

def test_one_off_fires_with_buttons_and_is_marked_fired(job_queue, freeze):
    rid = set_reminder("call mum", "2026-11-12T18:00", CTX)["id"]
    freeze(datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc))
    bot = fire(job_queue.live()[0])
    args, kwargs = bot.send_message.await_args
    assert args == (1, "⏰ call mum")
    buttons = kwargs["reply_markup"].inline_keyboard[0]
    assert [b.callback_data for b in buttons] == [f"rem:done:{rid}", f"rem:snooze:{rid}"]
    assert row(rid)["status"] == "fired"


def test_repeating_reminder_reschedules_itself(job_queue, freeze):
    rid = set_reminder("vitamins", "2026-11-12T18:00", CTX, repeat="daily")["id"]
    freeze(datetime(2026, 11, 12, 18, 0, 5, tzinfo=timezone.utc))
    fire(job_queue.live()[0])
    assert row(rid)["status"] == "active"
    assert row(rid)["fire_at"] == "2026-11-13T18:00:00+00:00"
    assert job_queue.live()[-1].when == datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)


def test_cancelled_reminder_does_not_fire(job_queue):
    rid = set_reminder("x", "2026-11-12T18:00", CTX)["id"]
    job = job_queue.live()[0]
    db.get_conn().execute("UPDATE reminders SET status='cancelled' WHERE id=?", (rid,))
    db.get_conn().commit()
    fire(job).send_message.assert_not_awaited()


# --- buttons ----------------------------------------------------------------

def test_done_closes_one_off(job_queue):
    rid = set_reminder("x", "2026-11-12T18:00", CTX)["id"]
    assert reminders.mark_done(rid, 1) == "✅ x"
    assert row(rid)["status"] == "done"
    assert job_queue.live() == []


def test_done_on_repeating_keeps_series():
    rid = set_reminder("x", "2026-11-12T18:00", CTX, repeat="daily")["id"]
    assert reminders.mark_done(rid, 1) == "✅ x (next: Thu 12 Nov 18:00)"
    assert row(rid)["status"] == "active"


def test_snooze_schedules_ten_minutes_later_and_refires(job_queue, freeze):
    rid = set_reminder("x", "2026-11-12T18:00", CTX)["id"]
    freeze(datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc))
    fire(job_queue.live()[0])
    assert reminders.snooze(rid, 1) == "💤 x (snoozed until Thu 12 Nov 18:10)"
    snooze_job = job_queue.get_jobs_by_name(f"snooze:{rid}")[0]
    assert snooze_job.when == datetime(2026, 11, 12, 18, 10, tzinfo=timezone.utc)
    bot = fire(snooze_job)
    assert bot.send_message.await_args.args == (1, "⏰ x (snoozed)")
    assert row(rid)["snooze_at"] is None


def test_buttons_ignore_other_chats():
    rid = set_reminder("x", "2026-11-12T18:00", CTX)["id"]
    assert reminders.mark_done(rid, 2) is None
    assert reminders.snooze(rid, 2) is None


# --- restore on startup -------------------------------------------------------

def _insert(fire_at, repeat="none", status="active", snooze_at=None):
    conn = db.get_conn()
    with conn:
        cur = conn.execute(
            "INSERT INTO reminders (chat_id, text, fire_at, repeat, status, snooze_at) VALUES (1, 't', ?, ?, ?, ?)",
            (timeutil.to_iso(fire_at), repeat, status, timeutil.to_iso(snooze_at) if snooze_at else None),
        )
    return cur.lastrowid


def test_restore_schedules_future_reminders(job_queue):
    _insert(NOW + timedelta(hours=2))
    assert reminders.restore(job_queue) == 1
    assert job_queue.live()[0].when == NOW + timedelta(hours=2)


def test_restore_delivers_missed_one_off_late(job_queue):
    rid = _insert(NOW - timedelta(hours=2))
    reminders.restore(job_queue)
    job = job_queue.live()[0]
    assert job.when == NOW + timedelta(seconds=1)  # right away
    bot = fire(job)
    assert "(late, was due Thu 12 Nov 08:00)" in bot.send_message.await_args.args[1]
    assert row(rid)["status"] == "fired"


def test_restore_skips_missed_repeats_to_next_future(job_queue):
    rid = _insert(NOW - timedelta(days=3), repeat="daily")
    reminders.restore(job_queue)
    assert row(rid)["fire_at"] == timeutil.to_iso(NOW + timedelta(days=1))
    assert job_queue.live()[0].when == NOW + timedelta(days=1)


def test_restore_reschedules_pending_snooze(job_queue):
    _insert(NOW - timedelta(hours=1), status="fired", snooze_at=NOW + timedelta(minutes=5))
    reminders.restore(job_queue)
    assert [j.name.split(":")[0] for j in job_queue.live()] == ["snooze"]


def test_restore_ignores_done_and_cancelled(job_queue):
    _insert(NOW + timedelta(hours=1), status="done")
    _insert(NOW + timedelta(hours=1), status="cancelled")
    _insert(NOW - timedelta(hours=1), status="fired")
    assert reminders.restore(job_queue) == 0
    assert job_queue.live() == []
