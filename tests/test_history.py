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


def test_tool_log_is_stored_between_user_and_reply():
    history.reset(4)
    history.add_exchange(4, "6*7?", "42", tool_log="Tools used: calculate -> 42")
    assert [m["role"] for m in history.get_history(4)] == ["user", "system", "assistant"]
    history.add_exchange(4, "hi", "hello")
    assert [m["role"] for m in history.get_history(4)][3:] == ["user", "assistant"]
    history.reset(4)


def test_tool_logs_do_not_count_toward_limit():
    msgs = []
    for i in range(3):
        msgs += [{"role": "user", "content": f"u{i}"},
                 {"role": "system", "content": f"log{i}"},
                 {"role": "assistant", "content": f"a{i}"}]
    trimmed = trim_history(msgs, limit=4)
    assert [m["content"] for m in trimmed] == ["u1", "log1", "a1", "u2", "log2", "a2"]


def test_trim_never_starts_with_an_orphaned_tool_log():
    msgs = [{"role": "user", "content": "u0"},
            {"role": "system", "content": "log0"},
            {"role": "assistant", "content": "a0"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"}]
    trimmed = trim_history(msgs, limit=3)
    assert [m["content"] for m in trimmed] == ["u1", "a1"]
