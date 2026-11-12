"""Shared helpers for the note tools (tags format, row -> dict)."""

import sqlite3

MAX_CONTENT_CHARS = 500


def encode_tags(tags: list[str] | None) -> str:
    """['Weak Spot', 'biology'] -> ',weak-spot,biology,'.

    Leading/trailing commas let `tags LIKE '%,weak-spot,%'` match whole tags
    only (so 'spot' doesn't match 'weak-spot').
    """
    cleaned = []
    for tag in tags or []:
        tag = "-".join(str(tag).lower().replace(",", " ").split())
        if tag and tag not in cleaned:
            cleaned.append(tag)
    return f",{','.join(cleaned)}," if cleaned else ""


def decode_tags(stored: str) -> list[str]:
    return [t for t in stored.split(",") if t]


def note_dict(row: sqlite3.Row, snippet: str | None = None) -> dict:
    content = row["content"]
    out = {
        "id": row["id"],
        "title": row["title"],
        "content": content if len(content) <= MAX_CONTENT_CHARS else content[:MAX_CONTENT_CHARS] + "…",
        "tags": decode_tags(row["tags"]),
        "saved": row["created_at"][:10],
    }
    if row["url"]:
        out["url"] = row["url"]
    if snippet:
        out["match"] = snippet
    return out
