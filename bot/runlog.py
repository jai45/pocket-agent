"""Structured run logs: one JSON line per agent run in data/logs/runs-YYYY-MM-DD.jsonl.

The text log says what happened line by line; this says what one RUN cost
and how it behaved (steps, tools, tokens, latency) in a form you can load
with `jq` or pandas. Message text and replies are deliberately left out:
they are already in the database, and logs get copied around more freely.
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot import config, timeutil, usage

logger = logging.getLogger(__name__)

TOOL_INPUT_CHARS = 200


def _short(value: dict) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= TOOL_INPUT_CHARS else text[:TOOL_INPUT_CHARS] + "…"


@dataclass
class RunLog:
    """Collects one agent run; `finish()` writes it."""

    chat_id: int
    trigger: str  # text | photo | voice | briefing | eval
    model: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = field(default_factory=lambda: timeutil.to_iso(timeutil.utc_now()))
    steps: list[dict] = field(default_factory=list)
    _start: float = field(default_factory=time.perf_counter)

    def add_step(self, step: int, response, latency_ms: float, tool_calls: list) -> None:
        """Record one model call and the tools it asked for."""
        inp, out, cache_read, cache_write = usage.tokens_of(response.usage)
        self.steps.append({
            "step": step,
            "stop_reason": response.stop_reason,
            "input_tokens": inp,
            "output_tokens": out,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "cost_usd": round(usage.cost_usd(self.model, inp, out, cache_read, cache_write), 6),
            "latency_ms": round(latency_ms),
            "tools": [
                {"name": c.name, "input": _short(c.input), "error": c.error, "latency_ms": round(c.latency_ms)}
                for c in tool_calls
            ],
        })

    def record(self, outcome: str) -> dict:
        """The finished JSON record (outcome: ok | error | overloaded)."""
        def total(key: str):
            return sum(s[key] for s in self.steps)
        return {
            "run_id": self.run_id,
            "chat_id": self.chat_id,
            "trigger": self.trigger,
            "model": self.model,
            "started_at": self.started_at,
            "latency_ms": round((time.perf_counter() - self._start) * 1000),
            "outcome": outcome,
            "steps": self.steps,
            "totals": {
                "steps": len(self.steps),
                "tool_calls": sum(len(s["tools"]) for s in self.steps),
                "input_tokens": total("input_tokens"),
                "output_tokens": total("output_tokens"),
                "cache_read_tokens": total("cache_read_tokens"),
                "cache_write_tokens": total("cache_write_tokens"),
                "cost_usd": round(total("cost_usd"), 6),
            },
        }

    def finish(self, outcome: str) -> dict:
        record = self.record(outcome)
        write(record)
        return record


def log_path(day: str | None = None) -> Path:
    return config.LOG_DIR / f"runs-{day or timeutil.local_today().isoformat()}.jsonl"


def write(record: dict) -> None:
    """Append one line. A full disk must never cost the user their reply."""
    try:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with log_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("Could not write run log")


def prune(now: datetime | None = None) -> int:
    """Delete run logs older than LOG_RETENTION_DAYS; return how many were removed."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=config.LOG_RETENTION_DAYS)).date().isoformat()
    removed = 0
    for path in config.LOG_DIR.glob("runs-*.jsonl"):
        if path.stem.removeprefix("runs-") < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed
