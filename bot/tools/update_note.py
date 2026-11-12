"""Edit an existing note."""

from bot import db, timeutil
from bot.notes_store import decode_tags, encode_tags
from bot.tool_context import ToolContext
from bot.tools.save_note import MAX_NOTE_CHARS

SPEC = {
    "name": "update_note",
    "description": (
        "Change a saved note's title, content, url or tags by id. Only the fields "
        "you pass are changed; tags replaces the whole tag list. To add to a note, "
        "pass the full new content. Find the id with search_notes first."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "title": {"type": "string"},
            "content": {"type": "string"},
            "url": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["id"],
    },
}


def update_note(
    id: int,  # noqa: A002 - matches the tool schema
    ctx: ToolContext,
    title: str | None = None,
    content: str | None = None,
    url: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM notes WHERE id = ? AND chat_id = ?", (id, ctx.chat_id)).fetchone()
    if row is None:
        return {"error": f"no note with id {id}"}
    changes: dict = {}
    if title is not None:
        if not title.strip():
            return {"error": "title can't be empty"}
        changes["title"] = title.strip()
    if content is not None:
        if not content.strip():
            return {"error": "content can't be empty"}
        if len(content) > MAX_NOTE_CHARS:
            return {"error": f"content too long (max {MAX_NOTE_CHARS} characters)"}
        changes["content"] = content.strip()
    if url is not None:
        changes["url"] = url.strip() or None
    if tags is not None:
        changes["tags"] = encode_tags(tags)
    if not changes:
        return {"error": "nothing to change"}
    changes["updated_at"] = timeutil.to_iso(timeutil.utc_now())
    sets = ", ".join(f"{k} = ?" for k in changes)
    with conn:  # the notes_au trigger re-indexes the note for search
        conn.execute(f"UPDATE notes SET {sets} WHERE id = ?", (*changes.values(), id))
    new = conn.execute("SELECT title, tags FROM notes WHERE id = ?", (id,)).fetchone()
    return {"updated": id, "title": new["title"], "tags": decode_tags(new["tags"]),
            "changed": [k for k in changes if k != "updated_at"]}
