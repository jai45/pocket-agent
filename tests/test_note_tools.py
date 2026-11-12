"""Tests for save/search/update/delete notes (SQLite FTS5)."""

import pytest

from bot.tool_context import ToolContext
from bot.tools.delete_note import delete_note
from bot.tools.save_note import save_note
from bot.tools.search_notes import fts_queries, search_notes
from bot.tools.update_note import update_note

CTX = ToolContext(chat_id=1)


@pytest.fixture
def notes():
    return {
        "photo": save_note("Photosynthesis", "Light reactions happen in the thylakoid membrane.", CTX,
                           tags=["Biology"])["id"],
        "krebs": save_note("Krebs cycle", "Happens in the mitochondrial matrix. Produces NADH.", CTX,
                           tags=["biology", "weak-spot"])["id"],
        "link": save_note("Async Python guide", "Explains asyncio event loops and tasks.", CTX,
                          url="https://example.com/async", tags=["python"])["id"],
    }


def test_save_normalises_tags():
    result = save_note("T", "C", CTX, tags=["Weak Spot", "weak-spot", "Bio, Chem"])
    assert result["tags"] == ["weak-spot", "bio-chem"]


def test_save_validation():
    assert "error" in save_note(" ", "content", CTX)
    assert "error" in save_note("title", "", CTX)


def test_search_matches_prefixes_and_ranks(notes):
    result = search_notes(CTX, query="thylak")
    assert [n["id"] for n in result["notes"]] == [notes["photo"]]
    assert "[thylakoid]" in result["notes"][0]["match"]


def test_search_falls_back_to_any_word(notes):
    # No note has both words, so the AND query misses and OR finds both.
    ids = {n["id"] for n in search_notes(CTX, query="mitochondrial asyncio")["notes"]}
    assert ids == {notes["krebs"], notes["link"]}


def test_search_by_tag_only_and_tag_plus_query(notes):
    assert [n["id"] for n in search_notes(CTX, tag="weak-spot")["notes"]] == [notes["krebs"]]
    assert [n["id"] for n in search_notes(CTX, query="light", tag="biology")["notes"]] == [notes["photo"]]
    # 'spot' is not the tag 'weak-spot'
    assert search_notes(CTX, tag="spot")["notes"] == []


def test_search_survives_fts_syntax_characters(notes):
    for nasty in ['"unclosed', "NEAR(a b", "light -dark", "a:b", "*", "AND OR"]:
        assert "notes" in search_notes(CTX, query=nasty)


def test_fts_queries_quotes_every_word():
    assert fts_queries('Krebs "cycle"') == ['"krebs"* "cycle"*', '"krebs"* OR "cycle"*']
    assert fts_queries("!!!") == []


def test_no_filter_lists_all_newest_first_titles_only(notes):
    result = search_notes(CTX)
    assert result["total"] == 3 and result["showing"] == 3
    assert [n["id"] for n in result["notes"]] == [notes["link"], notes["krebs"], notes["photo"]]
    assert result["notes"][1] == {
        "id": notes["krebs"], "title": "Krebs cycle", "tags": ["biology", "weak-spot"],
        "saved": result["notes"][1]["saved"]}
    assert "content" not in result["notes"][0]


def test_list_all_is_capped_with_total():
    from bot.tools.search_notes import MAX_LISTED
    for i in range(MAX_LISTED + 4):
        save_note(f"note {i}", "x", CTX)
    result = search_notes(CTX, query="  ")
    assert result["total"] == MAX_LISTED + 4 and result["showing"] == MAX_LISTED
    assert result["notes"][0]["title"] == f"note {MAX_LISTED + 3}"
    assert "older notes not shown" in result["note"]


def test_list_all_when_empty_and_per_chat(notes):
    assert search_notes(ToolContext(chat_id=2)) == {
        "total": 0, "showing": 0, "notes": [], "note": "no saved notes"}


def test_url_is_returned(notes):
    assert search_notes(CTX, query="asyncio")["notes"][0]["url"] == "https://example.com/async"


def test_update_reindexes_for_search(notes):
    update_note(notes["photo"], CTX, content="Chlorophyll absorbs red and blue light.", tags=["botany"])
    assert search_notes(CTX, query="thylakoid")["notes"] == []
    assert [n["id"] for n in search_notes(CTX, query="chlorophyll")["notes"]] == [notes["photo"]]
    assert search_notes(CTX, tag="botany")["notes"][0]["id"] == notes["photo"]


def test_update_validation(notes):
    assert "error" in update_note(notes["photo"], CTX)
    assert "error" in update_note(notes["photo"], CTX, title=" ")
    assert "error" in update_note(999, CTX, title="x")


def test_delete_removes_from_search(notes):
    assert delete_note(notes["krebs"], CTX) == {"deleted": notes["krebs"], "title": "Krebs cycle"}
    assert search_notes(CTX, query="krebs")["notes"] == []
    assert "error" in delete_note(notes["krebs"], CTX)


def test_notes_are_per_chat(notes):
    other = ToolContext(chat_id=2)
    assert search_notes(other, query="krebs")["notes"] == []
    assert "error" in update_note(notes["krebs"], other, title="hijack")
    assert "error" in delete_note(notes["krebs"], other)
