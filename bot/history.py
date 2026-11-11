"""Per-chat conversation history, stored in SQLite.

Only text is stored here: the user's message, an optional tool log, and
Claude's final reply. Raw tool_use/tool_result blocks and thinking live only
inside one run of the agent loop. That keeps trimming safe: we can never cut
a tool_use off from its tool_result, and we never edit history that contains
thinking blocks.

The tool log is a mid-conversation `system` message placed between the user
turn and the reply. Without it, Claude sees past replies like "the calculator
confirms..." with no evidence a tool ran, and concludes it made that up.

Every message is kept in the database (Phase 3 memory can use it); only the
last HISTORY_LIMIT user/assistant messages are loaded for each request.
"""

from bot import config, db


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


def get_history(chat_id: int, limit: int = config.HISTORY_LIMIT) -> list[dict]:
    """Load the recent conversation for one chat, oldest first.

    We fetch 2x the limit because tool logs don't count toward it (at most
    one per exchange), then trim precisely in Python.
    """
    rows = db.get_conn().execute(
        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (chat_id, limit * 2),
    ).fetchall()
    messages = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    return trim_history(messages, limit)


def add_exchange(chat_id: int, user_text: str, reply: str, tool_log: str | None = None) -> None:
    """Record one completed exchange (plus its tool log, if any) atomically.

    Saving everything in one transaction (only after success) means a failed
    model call never leaves a dangling user turn behind.
    """
    rows = [("user", user_text)]
    if tool_log:
        rows.append(("system", tool_log))
    rows.append(("assistant", reply))
    conn = db.get_conn()
    with conn:
        conn.executemany(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
            [(chat_id, role, content) for role, content in rows],
        )


def reset(chat_id: int) -> None:
    """Forget a chat's history."""
    conn = db.get_conn()
    with conn:
        conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
