"""Tests for the SQLite setup and migrations."""

import sqlite3

from bot import db


def test_fresh_database_is_at_latest_version(tmp_path):
    conn = db.init(tmp_path / "fresh.db")
    assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == len(db.MIGRATIONS)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"messages", "reminders", "todos", "schema_version"} <= tables


def test_migrate_twice_is_a_no_op(tmp_path):
    conn = db.init(tmp_path / "twice.db")
    conn.execute("INSERT INTO todos (chat_id, text) VALUES (1, 'keep me')")
    conn.commit()
    assert db.migrate(conn) == len(db.MIGRATIONS)
    assert conn.execute("SELECT text FROM todos").fetchone()[0] == "keep me"


def test_new_migration_is_applied_once(tmp_path, monkeypatch):
    conn = db.init(tmp_path / "upgrade.db")
    monkeypatch.setattr(db, "MIGRATIONS", db.MIGRATIONS + ["CREATE TABLE extra (x INTEGER);"])
    assert db.migrate(conn) == len(db.MIGRATIONS)
    conn.execute("SELECT x FROM extra")  # exists
    assert db.migrate(conn) == len(db.MIGRATIONS)


def test_creates_parent_directory(tmp_path):
    db.init(tmp_path / "nested" / "dir" / "pocket.db")
    assert (tmp_path / "nested" / "dir" / "pocket.db").exists()


def test_check_constraints_reject_bad_values():
    conn = db.get_conn()
    try:
        conn.execute("INSERT INTO todos (chat_id, text, priority) VALUES (1, 'x', 'urgent')")
        raise AssertionError("expected constraint failure")
    except sqlite3.IntegrityError:
        pass


def test_version_1_database_upgrades_to_latest(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    monkeypatch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:1])
    conn = db.init(path)
    conn.execute("INSERT INTO todos (chat_id, text) VALUES (1, 'from phase 2')")
    conn.commit()
    monkeypatch.undo()
    conn = db.init(path)  # restart on the new code
    assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == len(db.MIGRATIONS)
    assert conn.execute("SELECT text FROM todos").fetchone()[0] == "from phase 2"
    conn.execute("SELECT * FROM expenses, grocery_items, notes, profile_facts")
