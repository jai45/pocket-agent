"""Per-chat settings stored as JSON values in the `settings` table.

A tiny key/value store: new settings need no migration, just a new key.
"""

import json
from typing import Any

from bot import db


def get(chat_id: int, key: str, default: Any = None) -> Any:
    row = db.get_conn().execute(
        "SELECT value FROM settings WHERE chat_id = ? AND key = ?", (chat_id, key)
    ).fetchone()
    return json.loads(row["value"]) if row else default


def set(chat_id: int, key: str, value: Any) -> None:  # noqa: A001 - mirrors get()
    conn = db.get_conn()
    with conn:
        conn.execute(
            "INSERT INTO settings (chat_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT (chat_id, key) DO UPDATE SET value = excluded.value",
            (chat_id, key, json.dumps(value)),
        )
