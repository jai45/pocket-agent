"""SQLite storage with a tiny migration system.

The schema is a numbered list of SQL scripts. The `schema_version` table
remembers how many have run, so on startup we apply only the new ones.
To change the schema, APPEND a script; never edit one that has shipped,
because existing databases have already run it.
"""

import logging
import sqlite3
from pathlib import Path

from bot import config

logger = logging.getLogger(__name__)

MIGRATIONS: list[str] = [
    # 1: chat history, reminders, to-dos
    """
    CREATE TABLE messages (
        id         INTEGER PRIMARY KEY,
        chat_id    INTEGER NOT NULL,
        role       TEXT NOT NULL CHECK (role IN ('user', 'system', 'assistant')),
        content    TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    );
    CREATE INDEX idx_messages_chat ON messages (chat_id, id);

    CREATE TABLE reminders (
        id         INTEGER PRIMARY KEY,
        chat_id    INTEGER NOT NULL,
        text       TEXT NOT NULL,
        fire_at    TEXT NOT NULL,              -- next due time, ISO 8601 UTC
        repeat     TEXT NOT NULL DEFAULT 'none' CHECK (repeat IN ('none', 'daily', 'weekly')),
        status     TEXT NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active', 'fired', 'done', 'cancelled')),
        snooze_at  TEXT,                       -- pending snooze, ISO 8601 UTC
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    );
    CREATE INDEX idx_reminders_chat ON reminders (chat_id, status);

    CREATE TABLE todos (
        id         INTEGER PRIMARY KEY,
        chat_id    INTEGER NOT NULL,
        text       TEXT NOT NULL,
        due_date   TEXT,                       -- local calendar date YYYY-MM-DD
        priority   TEXT NOT NULL DEFAULT 'med' CHECK (priority IN ('low', 'med', 'high')),
        done_at    TEXT,                       -- ISO 8601 UTC, NULL while open
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    );
    CREATE INDEX idx_todos_chat ON todos (chat_id, done_at);
    """,
    # 2: expenses, grocery list, notes (+ full-text index), profile facts
    """
    CREATE TABLE expenses (
        id           INTEGER PRIMARY KEY,
        chat_id      INTEGER NOT NULL,
        amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),  -- whole cents: exact sums
        category     TEXT NOT NULL
                     CHECK (category IN ('food', 'transport', 'shopping', 'bills', 'fun', 'other')),
        note         TEXT NOT NULL DEFAULT '',
        spent_on     TEXT NOT NULL,              -- local calendar date YYYY-MM-DD
        created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    );
    CREATE INDEX idx_expenses_chat ON expenses (chat_id, spent_on);

    CREATE TABLE grocery_items (
        id         INTEGER PRIMARY KEY,
        chat_id    INTEGER NOT NULL,
        name       TEXT NOT NULL,                -- normalised: lower case, single spaces
        quantity   INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        UNIQUE (chat_id, name)                   -- lets "add milk" twice merge into x2
    );

    CREATE TABLE notes (
        id         INTEGER PRIMARY KEY,
        chat_id    INTEGER NOT NULL,
        title      TEXT NOT NULL,
        content    TEXT NOT NULL,
        url        TEXT,
        tags       TEXT NOT NULL DEFAULT '',     -- ",tag-one,tag-two," for exact LIKE matches
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        updated_at TEXT
    );
    CREATE INDEX idx_notes_chat ON notes (chat_id);

    -- Full-text index over notes. "External content" means it stores only the
    -- search index and reads text from `notes`; the triggers keep it in sync,
    -- so tool code never has to remember to update it.
    CREATE VIRTUAL TABLE notes_fts USING fts5(
        title, content, tags, content='notes', content_rowid='id'
    );
    CREATE TRIGGER notes_ai AFTER INSERT ON notes BEGIN
        INSERT INTO notes_fts (rowid, title, content, tags)
        VALUES (new.id, new.title, new.content, new.tags);
    END;
    CREATE TRIGGER notes_ad AFTER DELETE ON notes BEGIN
        INSERT INTO notes_fts (notes_fts, rowid, title, content, tags)
        VALUES ('delete', old.id, old.title, old.content, old.tags);
    END;
    CREATE TRIGGER notes_au AFTER UPDATE ON notes BEGIN
        INSERT INTO notes_fts (notes_fts, rowid, title, content, tags)
        VALUES ('delete', old.id, old.title, old.content, old.tags);
        INSERT INTO notes_fts (rowid, title, content, tags)
        VALUES (new.id, new.title, new.content, new.tags);
    END;

    CREATE TABLE profile_facts (
        id         INTEGER PRIMARY KEY,
        chat_id    INTEGER NOT NULL,
        fact       TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    );
    CREATE INDEX idx_facts_chat ON profile_facts (chat_id, id);
    """,
]

_conn: sqlite3.Connection | None = None


def _current_version(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        conn.commit()
        return 0
    return row[0]


def migrate(conn: sqlite3.Connection) -> int:
    """Apply any migrations newer than the stored version; return the new version.

    Each script and its version bump run in one transaction, so a failure
    leaves the database at the previous version instead of half-migrated.
    """
    version = _current_version(conn)
    for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
        logger.info("Applying database migration %d", number)
        conn.executescript(
            f"BEGIN;\n{script}\nUPDATE schema_version SET version = {number};\nCOMMIT;"
        )
        version = number
    return version


def init(path: Path | str | None = None) -> sqlite3.Connection:
    """Open (creating if needed) and migrate the database, then keep it open.

    One shared connection is enough: the bot runs on a single event loop and
    each query on a small local file takes well under a millisecond.
    """
    global _conn
    close()
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    migrate(conn)
    _conn = conn
    return conn


def get_conn() -> sqlite3.Connection:
    """Return the shared connection, opening the default database if needed."""
    return _conn if _conn is not None else init()


def close() -> None:
    """Close the shared connection (used by tests and on shutdown)."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
