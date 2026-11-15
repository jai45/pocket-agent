"""Structured run logs, and the nightly SQLite backup."""

import asyncio
import json
import sqlite3
from datetime import date, datetime, timezone
from types import SimpleNamespace

from bot import agent, config, db, history, runlog
from bot.jobs import backup


def text_response(text, stop="end_turn"):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=100, output_tokens=20,
                                                 cache_read_input_tokens=5000, cache_creation_input_tokens=0))


def tool_response():
    block = SimpleNamespace(type="tool_use", id="t1", name="calculate", input={"expression": "2+2"})
    return SimpleNamespace(content=[block], stop_reason="tool_use",
                           usage=SimpleNamespace(input_tokens=100, output_tokens=20))


def read_lines():
    (path,) = config.LOG_DIR.glob("runs-*.jsonl")
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_agent_run_writes_one_json_line(monkeypatch):
    responses = [tool_response(), text_response("It's 4.")]

    async def fake_create(messages, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(agent.llm, "create", fake_create)
    asyncio.run(agent.run_agent(1, "what is 2+2? secret words", trigger="text"))
    (record,) = read_lines()
    assert record["outcome"] == "ok" and record["trigger"] == "text"
    assert record["totals"]["steps"] == 2 and record["totals"]["tool_calls"] == 1
    assert record["totals"]["cache_read_tokens"] == 5000
    assert record["steps"][0]["tools"][0]["name"] == "calculate"
    assert "secret words" not in json.dumps(record)  # message text is never logged
    assert len(record["run_id"]) == 12


def test_failed_run_is_logged_as_overloaded(monkeypatch):
    async def overloaded(messages, **kwargs):
        raise agent.llm.ModelUnavailable("529")

    monkeypatch.setattr(agent.llm, "create", overloaded)
    try:
        asyncio.run(agent.run_agent(1, "hi"))
    except agent.llm.ModelUnavailable:
        pass
    assert read_lines()[0]["outcome"] == "overloaded"
    assert history.get_history(1) == []  # nothing half-saved


def test_long_tool_input_is_truncated():
    assert len(runlog._short({"text": "x" * 500})) == runlog.TOOL_INPUT_CHARS + 1


def test_prune_deletes_logs_older_than_retention():
    config.LOG_DIR.mkdir(parents=True)
    (config.LOG_DIR / "runs-2026-09-01.jsonl").write_text("{}\n")
    (config.LOG_DIR / "runs-2026-11-10.jsonl").write_text("{}\n")
    assert runlog.prune(datetime(2026, 11, 14, tzinfo=timezone.utc)) == 1
    assert [p.name for p in config.LOG_DIR.iterdir()] == ["runs-2026-11-10.jsonl"]


def test_backup_is_a_readable_copy_and_keeps_seven():
    history.add_exchange(1, "hello", "hi")
    for day in range(1, 10):
        path = backup.backup_now(today=date(2026, 11, day))
    names = sorted(p.name for p in config.BACKUP_DIR.iterdir())
    assert names == [f"pocket-2026-11-0{d}.db" for d in range(3, 10)]
    copy = sqlite3.connect(path)
    assert copy.execute("SELECT content FROM messages WHERE role = 'user'").fetchone()[0] == "hello"
    copy.close()
    assert db.get_conn().execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2  # original untouched


def test_backup_is_scheduled_nightly(job_queue):
    backup.schedule(job_queue)
    (job,) = job_queue.get_jobs_by_name(backup.JOB_NAME)
    assert job.when.hour == 3 and job.when.tzinfo == config.TIMEZONE
