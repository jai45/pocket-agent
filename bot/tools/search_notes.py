"""Full-text search over the user's notes (SQLite FTS5), or list them all."""

import re

from bot import db
from bot.notes_store import decode_tags, encode_tags, note_dict
from bot.tool_context import ToolContext

MAX_RESULTS = 5
MAX_LISTED = 20

SPEC = {
    "name": "search_notes",
    "description": (
        "Search the user's saved notes and links by words (matches title, content "
        "and tags; prefixes count, so 'photo' finds 'photosynthesis'). Optionally "
        "filter by a tag, e.g. tag='weak-spot' for quiz weak spots; with a tag and "
        "no query it lists the newest notes with that tag. Call with NO query and "
        "no tag to list all saved notes (newest first, titles only, with the total). "
        "Use this, not memory, whenever the user asks what they saved or about "
        "something they saved. Returns note ids for update_note / delete_note."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Words to look for."},
            "tag": {"type": "string", "description": "Only notes with this tag."},
        },
    },
}


def fts_queries(query: str) -> list[str]:
    """Turn free text into safe FTS5 queries: all words first, then any word.

    Raw user text can contain FTS5 syntax (quotes, '-', ':', AND/OR) that
    would error or change the meaning, so we keep only word characters and
    quote each word as a prefix search.
    """
    words = re.findall(r"\w+", query.lower())
    if not words:
        return []
    terms = [f'"{w}"*' for w in words]
    queries = [" ".join(terms)]  # implicit AND
    if len(terms) > 1:
        queries.append(" OR ".join(terms))
    return queries


def list_all(chat_id: int) -> dict:
    """No filter at all: an overview of every note, newest first.

    Titles only (no content) so a long collection stays cheap; the total
    tells Claude (and the user) when there are more than shown.
    """
    conn = db.get_conn()
    total = conn.execute("SELECT COUNT(*) FROM notes WHERE chat_id = ?", (chat_id,)).fetchone()[0]
    rows = conn.execute(
        "SELECT id, title, tags, created_at FROM notes WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (chat_id, MAX_LISTED),
    ).fetchall()
    notes = [
        {"id": r["id"], "title": r["title"], "tags": decode_tags(r["tags"]), "saved": r["created_at"][:10]}
        for r in rows
    ]
    result: dict = {"total": total, "showing": len(notes), "notes": notes}
    if total == 0:
        result["note"] = "no saved notes"
    elif total > len(notes):
        result["note"] = "older notes not shown; search by words or tag to find them"
    return result


def search_notes(ctx: ToolContext, query: str = "", tag: str | None = None) -> dict:
    """Best matches first (bm25 rank), only this chat's notes. No filter = list all."""
    tag_filter = encode_tags([tag]) if tag else ""
    if not query.strip() and not tag_filter:
        return list_all(ctx.chat_id)
    conn = db.get_conn()
    tag_sql = " AND n.tags LIKE ?" if tag_filter else ""
    tag_params = (f"%{tag_filter}%",) if tag_filter else ()

    if not query.strip():
        rows = conn.execute(
            f"SELECT n.* FROM notes n WHERE n.chat_id = ?{tag_sql} ORDER BY n.id DESC LIMIT ?",
            (ctx.chat_id, *tag_params, MAX_RESULTS),
        ).fetchall()
        notes = [note_dict(r) for r in rows]
    else:
        notes = []
        for fts_query in fts_queries(query):
            rows = conn.execute(
                "SELECT n.*, snippet(notes_fts, 1, '[', ']', '…', 12) AS snip "
                "FROM notes_fts JOIN notes n ON n.id = notes_fts.rowid "
                f"WHERE notes_fts MATCH ? AND n.chat_id = ?{tag_sql} "
                "ORDER BY bm25(notes_fts) LIMIT ?",
                (fts_query, ctx.chat_id, *tag_params, MAX_RESULTS),
            ).fetchall()
            if rows:
                notes = [note_dict(r, r["snip"]) for r in rows]
                break
    return {"notes": notes} if notes else {"notes": [], "note": "no matching notes"}
