"""Nightly SQLite backup, scheduled inside the bot (no cron to set up).

sqlite3's backup() copies a consistent snapshot even while the bot is
writing, which a plain file copy can't promise. We keep the newest
BACKUP_KEEP files, so a bad day can be rolled back for a week.
"""

import logging
import sqlite3
from datetime import date
from pathlib import Path

from telegram.ext import ContextTypes, JobQueue

from bot import config, db, runlog, timeutil
from bot.jobs.briefing import parse_time

logger = logging.getLogger(__name__)

JOB_NAME = "nightly-backup"


def backup_now(dest_dir: Path | None = None, today: date | None = None) -> Path:
    """Write pocket-YYYY-MM-DD.db and prune old ones; return the new file's path.

    Runs on the event loop thread because the shared sqlite connection is
    tied to it; for a small personal DB this takes milliseconds.
    """
    dest_dir = dest_dir or config.BACKUP_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"pocket-{(today or timeutil.local_today()).isoformat()}.db"
    target = sqlite3.connect(path)
    try:
        db.get_conn().backup(target)
    finally:
        target.close()
    prune(dest_dir)
    return path


def prune(dest_dir: Path, keep: int | None = None) -> list[Path]:
    """Delete all but the newest `keep` backups (names sort by date)."""
    keep = config.BACKUP_KEEP if keep is None else keep
    backups = sorted(dest_dir.glob("pocket-*.db"))
    old = backups[:-keep] if keep else backups
    for path in old:
        path.unlink(missing_ok=True)
    return old


async def backup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue callback: back up the DB and clear out expired run logs."""
    try:
        path = backup_now()
        removed = runlog.prune()
        logger.info("backup_done path=%s old_run_logs_removed=%d", path, removed)
    except Exception:  # noqa: BLE001 - a failed backup must not kill the scheduler
        logger.exception("Nightly backup failed")


def schedule(job_queue: JobQueue) -> None:
    """Run every night at BACKUP_TIME local time."""
    when = parse_time(config.BACKUP_TIME)
    if when is None:
        logger.warning("Bad BACKUP_TIME %r; nightly backup disabled", config.BACKUP_TIME)
        return
    job_queue.run_daily(backup_job, when.replace(tzinfo=config.TIMEZONE), name=JOB_NAME)
