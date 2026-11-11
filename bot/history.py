"""Per-chat conversation history.

Only plain text turns are stored here: the user's message and Claude's final
reply. Tool calls, tool results and thinking live only inside one run of the
agent loop. That keeps trimming safe: we can never cut a tool_use off from
its tool_result, and we never edit history that contains thinking blocks.
"""

from bot import config

# chat_id -> list of {"role": ..., "content": str}. In memory, so history is
# lost on restart; persistence comes in a later phase.
_histories: dict[int, list[dict]] = {}


def trim_history(history: list[dict], limit: int = config.HISTORY_LIMIT) -> list[dict]:
    """Keep the last `limit` messages, making sure the first one is from the user.

    Trimming bounds cost and context size. The API rejects a conversation
    that starts with an assistant turn, so we drop any leading ones.
    """
    trimmed = history[-limit:]
    while trimmed and trimmed[0]["role"] != "user":
        trimmed = trimmed[1:]
    return trimmed


def get_history(chat_id: int) -> list[dict]:
    """Return a copy so callers can build on it without mutating stored state."""
    return list(_histories.get(chat_id, []))


def add_exchange(chat_id: int, user_text: str, reply: str) -> None:
    """Record one completed user/assistant exchange, then trim.

    Saving both halves together (only after success) means a failed model
    call never leaves a dangling user turn behind.
    """
    history = _histories.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": reply})
    _histories[chat_id] = trim_history(history)


def reset(chat_id: int) -> None:
    """Forget a chat's history."""
    _histories.pop(chat_id, None)
