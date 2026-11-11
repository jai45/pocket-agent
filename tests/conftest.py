"""Shared test setup.

config.py requires secrets at import time; tests never use real values or
the network, so dummy values are enough. Every test also gets a fresh
temporary SQLite file, so tests can't see each other's data or touch
data/pocket.db.
"""

import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from datetime import datetime, timezone  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

import pytest  # noqa: E402

from bot import config, db, reminders, timeutil  # noqa: E402


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    db.init(tmp_path / "test.db")
    reminders.attach(None)
    yield
    reminders.attach(None)
    db.close()


@pytest.fixture
def london(monkeypatch):
    """Pin the user's timezone so date maths in tests is deterministic."""
    monkeypatch.setattr(config, "TIMEZONE", ZoneInfo("Europe/London"))


@pytest.fixture
def freeze(monkeypatch):
    """Call freeze(datetime) to set "now" (UTC) for timeutil.utc_now()."""
    def _freeze(dt: datetime) -> None:
        monkeypatch.setattr(timeutil, "utc_now", lambda: dt.astimezone(timezone.utc))
    return _freeze


class FakeJob:
    def __init__(self, queue, callback, when, data, name, chat_id):
        self.queue, self.callback, self.when = queue, callback, when
        self.data, self.name, self.chat_id = data, name, chat_id
        self.removed = False

    def schedule_removal(self):
        self.removed = True


class FakeJobQueue:
    """Records run_once calls instead of scheduling anything."""

    def __init__(self):
        self.jobs: list[FakeJob] = []

    def run_once(self, callback, when, data=None, name=None, chat_id=None):
        job = FakeJob(self, callback, when, data, name, chat_id)
        self.jobs.append(job)
        return job

    def get_jobs_by_name(self, name):
        return [j for j in self.jobs if j.name == name and not j.removed]

    def live(self):
        return [j for j in self.jobs if not j.removed]


@pytest.fixture
def job_queue():
    queue = FakeJobQueue()
    reminders.attach(queue)
    return queue
