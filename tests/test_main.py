"""Tests for the pure helpers in bot.main (no network, no Telegram)."""

import os

# config.py requires these at import time; tests never use real values.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from bot.main import split_message, trim_history  # noqa: E402


def test_split_short_message_is_untouched():
    assert split_message("hello") == ["hello"]


def test_split_long_message_respects_limit_and_keeps_content():
    text = "\n".join(f"line {i}" for i in range(2000))
    chunks = split_message(text, limit=100)
    assert all(len(c) <= 100 for c in chunks)
    assert "\n".join(chunks) == text


def test_split_without_whitespace_hard_cuts():
    chunks = split_message("x" * 250, limit=100)
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_trim_keeps_last_n():
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(30)]
    trimmed = trim_history(history, limit=20)
    assert len(trimmed) == 20
    assert trimmed[-1]["content"] == "29"


def test_trim_never_starts_with_assistant():
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(21)]
    trimmed = trim_history(history, limit=20)
    assert trimmed[0]["role"] == "user"
    assert len(trimmed) == 19
