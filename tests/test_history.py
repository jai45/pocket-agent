"""Tests for per-chat history storage and trimming."""

from bot import history
from bot.history import trim_history


def _alternating(n: int) -> list[dict]:
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(n)]


def test_trim_keeps_last_n():
    trimmed = trim_history(_alternating(30), limit=20)
    assert len(trimmed) == 20
    assert trimmed[-1]["content"] == "29"


def test_trim_never_starts_with_assistant():
    trimmed = trim_history(_alternating(21), limit=20)
    assert trimmed[0]["role"] == "user"
    assert len(trimmed) == 19


def test_add_exchange_and_reset_are_per_chat():
    history.reset(1)
    history.reset(2)
    history.add_exchange(1, "hi", "hello")
    assert history.get_history(1) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    assert history.get_history(2) == []
    history.reset(1)
    assert history.get_history(1) == []


def test_get_history_returns_a_copy():
    history.reset(3)
    history.add_exchange(3, "a", "b")
    history.get_history(3).append({"role": "user", "content": "sneaky"})
    assert len(history.get_history(3)) == 2
