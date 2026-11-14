"""The daily morning briefing: the same agent loop, started by a timer.

A message trigger always runs (someone asked). A scheduled trigger must
decide whether acting is worthwhile right now, and nobody is waiting to
answer follow-up questions, so the prompt has to be self-contained.
"""

import logging
import re
from datetime import datetime, time, timedelta
from functools import partial

from telegram.ext import ContextTypes, JobQueue

from bot import config, db, settings, timeutil
from bot.agent import AgentResult, run_agent
from bot.replies import send_markdown

logger = logging.getLogger(__name__)

HISTORY_TEXT = "[scheduled: morning briefing]"
QUIET_MINUTES = 30
OFF = "off"
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def parse_time(value: str) -> time | None:
    """'7:30' / '07:30' -> time(7, 30); anything else -> None."""
    match = _TIME_RE.match(value.strip())
    return time(int(match[1]), int(match[2])) if match else None


def briefing_time(chat_id: int) -> str:
    """The chat's HH:MM, or 'off'. Falls back to BRIEFING_TIME from .env."""
    return settings.get(chat_id, "briefing_time", config.BRIEFING_TIME)


def topics(chat_id: int) -> list[str]:
    """The chat's topics, keeping only ones that still exist in NEWS_FEEDS."""
    chosen = settings.get(chat_id, "topics", config.DEFAULT_TOPICS)
    return [t for t in chosen if t in config.NEWS_FEEDS]


def build_prompt(chat_id: int) -> str:
    """The system-generated 'user message' for the briefing."""
    topic_list = ", ".join(topics(chat_id)) or "general news"
    return (
        "Create my morning briefing: weather, today's to-dos and reminders, "
        f"3 headlines on my topics ({topic_list}). Under 12 lines. "
        # Explicit counting rules: without them the model gave 3 headlines
        # PER topic and treated blank lines as free (19 lines in testing).
        "That means 3 headlines in total across all topics, and fewer than 12 "
        "lines counting every line, with no blank lines. "
        "This is an automatic scheduled message and I'm not waiting to reply, "
        "so don't ask me any questions."
    )


def _last_user_message_at(chat_id: int) -> datetime | None:
    """When the user last really wrote (the briefing's own entry doesn't count)."""
    row = db.get_conn().execute(
        "SELECT created_at FROM messages WHERE chat_id = ? AND role = 'user' "
        "AND content NOT LIKE '[scheduled:%' ORDER BY id DESC LIMIT 1",
        (chat_id,),
    ).fetchone()
    return timeutil.from_iso(row["created_at"].replace("Z", "+00:00")) if row else None


def skip_reason(chat_id: int) -> str | None:
    """Why the scheduled briefing shouldn't go out now, or None to send it."""
    today = timeutil.local_today().isoformat()
    if settings.get(chat_id, "last_briefing_date") == today:
        return "already sent today"
    last = _last_user_message_at(chat_id)
    if last and timeutil.utc_now() - last < timedelta(minutes=QUIET_MINUTES):
        return f"user chatted in the last {QUIET_MINUTES} minutes"
    return None


async def run_briefing(bot, chat_id: int) -> AgentResult:
    """Build and send the briefing (no checks: callers decide whether to run).

    The date is marked BEFORE generating, so a crash or retry can never send
    two: at most one per day, at the cost of none if something fails.
    """
    settings.set(chat_id, "last_briefing_date", timeutil.local_today().isoformat())
    result = await run_agent(chat_id, build_prompt(chat_id), history_text=HISTORY_TEXT, model=config.FAST_MODEL)
    await send_markdown(partial(bot.send_message, chat_id), result.text)
    logger.info("briefing_sent chat=%s tools=%s", chat_id, [c.name for c in result.trace])
    return result


async def briefing_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue callback. There is no Update here: the chat comes from the job."""
    chat_id = context.job.chat_id
    reason = skip_reason(chat_id)
    if reason:
        logger.info("briefing_skipped chat=%s reason=%s", chat_id, reason)
        return
    try:
        await run_briefing(context.bot, chat_id)
    except Exception:  # noqa: BLE001 - a failed briefing must not kill the scheduler
        logger.exception("Briefing failed for chat %s", chat_id)


def job_name(chat_id: int) -> str:
    return f"briefing:{chat_id}"


def schedule(job_queue: JobQueue, chat_id: int) -> str:
    """(Re)create the chat's daily job from its saved time; return that time or 'off'.

    The whole job is derived from the DB setting, so rebuilding it on
    startup with run_daily loses nothing.
    """
    for job in job_queue.get_jobs_by_name(job_name(chat_id)):
        job.schedule_removal()
    when = briefing_time(chat_id)
    parsed = parse_time(when) if when != OFF else None
    if parsed is None:
        return OFF
    # tzinfo on the time makes 07:30 mean 07:30 local, across DST changes.
    job_queue.run_daily(
        briefing_job, parsed.replace(tzinfo=config.TIMEZONE), name=job_name(chat_id), chat_id=chat_id
    )
    return when


def restore(job_queue: JobQueue) -> None:
    """Schedule a briefing for every allowed user (private chat id == user id)."""
    for chat_id in sorted(config.ALLOWED_USER_IDS):
        logger.info("Briefing for chat %s: %s", chat_id, schedule(job_queue, chat_id))
