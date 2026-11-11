"""Per-chat conversation history.

Only text is stored here: the user's message, an optional tool log, and
Claude's final reply. Raw tool_use/tool_result blocks and thinking live only
inside one run of the agent loop. That keeps trimming safe: we can never cut
a tool_use off from its tool_result, and we never edit history that contains
thinking blocks.

The tool log is a mid-conversation `system` message placed between the user
turn and the reply. Without it, Claude sees past replies like "the calculator
confirms..." with no evidence a tool ran, and concludes it made that up.
"""

from bot import config

# chat_id -> list of {"role": "user"|"system"|"assistant", "content": str}. In memory, so history is
# lost on restart; persistence comes in a later phase.
_histories: dict[int, list[dict]] = {}


def trim_history(history: list[dict], limit: int = config.HISTORY_LIMIT) -> list[dict]:
    """Keep the last `limit` user/assistant messages, starting with a user turn.

    Trimming bounds cost and context size. Tool-log system notes don't count
    toward the limit; they travel with their exchange. The API rejects a
    conversation that starts with anything but a user turn, so any leading
    assistant reply or orphaned tool log is dropped too.
    """
    start, counted = len(history), 0
    while start > 0 and counted < limit:
        start -= 1
        if history[start]["role"] != "system":
            counted += 1
    trimmed = history[start:]
    while trimmed and trimmed[0]["role"] != "user":
        trimmed = trimmed[1:]
    return trimmed


def get_history(chat_id: int) -> list[dict]:
    """Return a copy so callers can build on it without mutating stored state."""
    return list(_histories.get(chat_id, []))


def add_exchange(chat_id: int, user_text: str, reply: str, tool_log: str | None = None) -> None:
    """Record one completed exchange (plus its tool log, if any), then trim.

    Saving everything together (only after success) means a failed model
    call never leaves a dangling user turn behind.
    """
    history = _histories.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})
    if tool_log:
        history.append({"role": "system", "content": tool_log})
    history.append({"role": "assistant", "content": reply})
    _histories[chat_id] = trim_history(history)


def reset(chat_id: int) -> None:
    """Forget a chat's history."""
    _histories.pop(chat_id, None)
