"""Reminder scheduling on top of python-telegram-bot's JobQueue.

The JobQueue lives in memory, so a restart wipes every job. The database is
the source of truth and the jobs are a cache we rebuild from it: every
change is saved first, then (re)scheduled, and restore() rebuilds all jobs
on startup.

Each occurrence is a one-off job. When a repeating reminder fires we compute
the next occurrence, save it, and schedule that. This keeps one code path
for "scheduled now" and "rescheduled after a restart".
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, JobQueue

from bot import config, db, timeutil

logger = logging.getLogger(__name__)

SNOOZE_MINUTES = 10
# A reminder delivered more than this after its time is labelled "late".
LATE_AFTER = timedelta(minutes=1)
REPEAT_STEP = {"daily": timedelta(days=1), "weekly": timedelta(weeks=1)}

# Set by attach() at startup; None in tests, which then skip scheduling.
_job_queue: JobQueue | None = None


def attach(job_queue: JobQueue | None) -> None:
    """Give this module the bot's JobQueue so tools can schedule jobs."""
    global _job_queue
    _job_queue = job_queue


def get(reminder_id: int, chat_id: int) -> sqlite3.Row | None:
    """Fetch one reminder, only if it belongs to this chat."""
    return db.get_conn().execute(
        "SELECT * FROM reminders WHERE id = ? AND chat_id = ?", (reminder_id, chat_id)
    ).fetchone()


def _load(reminder_id: int) -> sqlite3.Row | None:
    return db.get_conn().execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()


def _update(reminder_id: int, **fields) -> None:
    sets = ", ".join(f"{name} = ?" for name in fields)
    conn = db.get_conn()
    with conn:
        conn.execute(f"UPDATE reminders SET {sets} WHERE id = ?", (*fields.values(), reminder_id))


def next_occurrence(fire_at: datetime, repeat: str, after: datetime) -> datetime:
    """Next time a repeating reminder is due, strictly after `after` (UTC).

    We step in LOCAL wall-clock time, so "8am daily" stays at 8am across a
    daylight-saving change instead of drifting to 7am or 9am.
    """
    step = REPEAT_STEP[repeat]
    local = fire_at.astimezone(config.TIMEZONE).replace(tzinfo=None)
    candidate = fire_at
    while candidate <= after:
        local += step
        candidate = local.replace(tzinfo=config.TIMEZONE).astimezone(timezone.utc)
    return candidate


def keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    """Done / Snooze buttons. callback_data is how Telegram tells us which was tapped."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Done", callback_data=f"rem:done:{reminder_id}"),
        InlineKeyboardButton(f"💤 Snooze {SNOOZE_MINUTES}m", callback_data=f"rem:snooze:{reminder_id}"),
    ]])


def _job_names(reminder_id: int) -> tuple[str, str]:
    return f"reminder:{reminder_id}", f"snooze:{reminder_id}"


def unschedule(reminder_id: int) -> None:
    """Remove any pending jobs for a reminder (safe if there are none)."""
    if _job_queue is None:
        return
    for name in _job_names(reminder_id):
        for job in _job_queue.get_jobs_by_name(name):
            job.schedule_removal()


def schedule(row: sqlite3.Row) -> None:
    """Create jobs matching the reminder's saved state, replacing old ones.

    Times already in the past are scheduled a second from now, so a missed
    reminder is delivered (late) rather than silently dropped.
    """
    if _job_queue is None:
        return
    unschedule(row["id"])
    soon = timeutil.utc_now() + timedelta(seconds=1)
    fire_name, snooze_name = _job_names(row["id"])
    if row["status"] == "active":
        when = max(timeutil.from_iso(row["fire_at"]), soon)
        _job_queue.run_once(_fire, when, data={"id": row["id"]}, name=fire_name, chat_id=row["chat_id"])
    if row["snooze_at"] and row["status"] in ("active", "fired"):
        when = max(timeutil.from_iso(row["snooze_at"]), soon)
        _job_queue.run_once(_fire_snooze, when, data={"id": row["id"]}, name=snooze_name, chat_id=row["chat_id"])


async def _fire(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: send the reminder, then advance or close it."""
    row = _load(context.job.data["id"])
    if row is None or row["status"] != "active":
        return  # cancelled or done since it was scheduled
    now = timeutil.utc_now()
    due = timeutil.from_iso(row["fire_at"])
    text = f"⏰ {row['text']}"
    if now - due > LATE_AFTER:
        text += f"\n(late, was due {timeutil.format_local(due)})"
    await context.bot.send_message(row["chat_id"], text, reply_markup=keyboard(row["id"]))
    logger.info("reminder_fired id=%d repeat=%s", row["id"], row["repeat"])

    if row["repeat"] == "none":
        # "fired" (not "active") so a restart doesn't deliver it again.
        _update(row["id"], status="fired")
    else:
        _update(row["id"], fire_at=timeutil.to_iso(next_occurrence(due, row["repeat"], now)))
        schedule(_load(row["id"]))


async def _fire_snooze(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: re-send a snoozed reminder."""
    row = _load(context.job.data["id"])
    if row is None or not row["snooze_at"] or row["status"] not in ("active", "fired"):
        return
    _update(row["id"], snooze_at=None)
    await context.bot.send_message(row["chat_id"], f"⏰ {row['text']} (snoozed)", reply_markup=keyboard(row["id"]))


def mark_done(reminder_id: int, chat_id: int) -> str | None:
    """Handle the Done button; return the text to show, or None if unknown."""
    row = get(reminder_id, chat_id)
    if row is None:
        return None
    had_snooze = row["snooze_at"] is not None
    if row["repeat"] == "none":
        _update(reminder_id, status="done", snooze_at=None)
        unschedule(reminder_id)
        return f"✅ {row['text']}"
    if had_snooze:
        _update(reminder_id, snooze_at=None)
        schedule(_load(reminder_id))
    # Repeating: the next occurrence is already scheduled; just acknowledge.
    return f"✅ {row['text']} (next: {timeutil.format_local(timeutil.from_iso(row['fire_at']))})"


def snooze(reminder_id: int, chat_id: int) -> str | None:
    """Handle the Snooze button; return the text to show, or None if unknown."""
    row = get(reminder_id, chat_id)
    if row is None or row["status"] not in ("active", "fired"):
        return None
    until = timeutil.utc_now() + timedelta(minutes=SNOOZE_MINUTES)
    _update(reminder_id, snooze_at=timeutil.to_iso(until))
    schedule(_load(reminder_id))
    return f"💤 {row['text']} (snoozed until {timeutil.format_local(until)})"


def restore(job_queue: JobQueue) -> int:
    """Rebuild jobs from the database on startup; return how many reminders.

    - future reminders: scheduled as normal
    - one-off reminders missed while the bot was down: delivered now, as "late"
    - repeating reminders that missed occurrences: skip ahead to the next
      future time (no burst of stale alerts)
    - pending snoozes: rescheduled too
    """
    attach(job_queue)
    now = timeutil.utc_now()
    rows = db.get_conn().execute(
        "SELECT * FROM reminders WHERE status = 'active' "
        "OR (status = 'fired' AND snooze_at IS NOT NULL)"
    ).fetchall()
    for row in rows:
        due = timeutil.from_iso(row["fire_at"])
        if row["status"] == "active" and row["repeat"] != "none" and due <= now:
            _update(row["id"], fire_at=timeutil.to_iso(next_occurrence(due, row["repeat"], now)))
            row = _load(row["id"])
        schedule(row)
    logger.info("Restored %d reminder(s) from the database", len(rows))
    return len(rows)
