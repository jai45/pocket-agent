"""Tests for the Telegram photo and voice handlers (Telegram and model mocked)."""

import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from bot import config, main
from bot.agent import AgentResult
from bot.media import MAX_UPLOAD_BYTES, voice


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (10, 120, 10)).save(buf, format="JPEG")
    return buf.getvalue()


def _file(data: bytes):
    tg_file = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=bytearray(data)))
    return AsyncMock(return_value=tg_file)


def _update(**message_fields):
    update = MagicMock()
    update.effective_chat.id = 1
    update.effective_user.id = 1
    update.message.reply_text = AsyncMock()
    for key, value in message_fields.items():
        setattr(update.message, key, value)
    return update


@pytest.fixture
def agent_calls(monkeypatch):
    """Capture what reaches the agent; resolve history_text like run_agent would."""
    calls = []

    async def fake_run_agent(chat_id, content, history_text=None):
        if history_text is not None and not isinstance(history_text, str):
            history_text = await history_text
        calls.append({"content": content, "history_text": history_text})
        return AgentResult(text="ok")

    monkeypatch.setattr(config, "ALLOWED_USER_IDS", {1})
    monkeypatch.setattr(main, "run_agent", fake_run_agent)
    monkeypatch.setattr(main, "keep_typing", AsyncMock())
    monkeypatch.setattr(main, "send_formatted", AsyncMock())
    return calls


def test_photo_reaches_agent_as_image_then_text(agent_calls, monkeypatch):
    monkeypatch.setattr(main.vision, "label_image", AsyncMock(return_value="green square"))
    small, large = SimpleNamespace(file_size=100, get_file=_file(b"")), \
        SimpleNamespace(file_size=2000, get_file=_file(_jpeg()))
    update = _update(photo=[small, large], caption=None)
    asyncio.run(main.handle_photo(update, MagicMock()))

    (call,) = agent_calls
    image, text = call["content"]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg"
    assert text == {"type": "text", "text": "What's in this photo?"}
    assert call["history_text"] == "[photo: green square]"
    large.get_file.assert_awaited_once()
    small.get_file.assert_not_awaited()  # only the largest size is downloaded


def test_photo_caption_is_used_and_kept_in_history(agent_calls, monkeypatch):
    monkeypatch.setattr(main.vision, "label_image", AsyncMock(return_value="grocery receipt"))
    update = _update(photo=[SimpleNamespace(file_size=2000, get_file=_file(_jpeg()))], caption=" log this ")
    asyncio.run(main.handle_photo(update, MagicMock()))
    assert agent_calls[0]["content"][1]["text"] == "log this"
    assert agent_calls[0]["history_text"] == "[photo: grocery receipt] log this"


def test_oversized_photo_is_refused_without_download(agent_calls):
    photo = SimpleNamespace(file_size=MAX_UPLOAD_BYTES + 1, get_file=_file(b""))
    update = _update(photo=[photo], caption=None)
    asyncio.run(main.handle_photo(update, MagicMock()))
    assert "under 10 MB" in update.message.reply_text.await_args.args[0]
    photo.get_file.assert_not_awaited()
    assert agent_calls == []


def test_unreadable_photo_gets_friendly_reply(agent_calls):
    update = _update(photo=[SimpleNamespace(file_size=10, get_file=_file(b"junk"))], caption=None)
    asyncio.run(main.handle_photo(update, MagicMock()))
    assert "couldn't open" in update.message.reply_text.await_args.args[0]
    assert agent_calls == []


def test_voice_transcript_is_echoed_in_italics_then_answered(agent_calls, monkeypatch):
    monkeypatch.setattr(voice, "is_available", lambda: True)
    monkeypatch.setattr(voice, "transcribe", AsyncMock(return_value="Add milk & eggs"))
    note = SimpleNamespace(file_size=5000, get_file=_file(b"ogg"))
    update = _update(voice=note)
    asyncio.run(main.handle_voice(update, MagicMock()))

    echo = update.message.reply_text.await_args_list[0]
    assert echo.args == ("🎙 <i>Add milk &amp; eggs</i>",)
    assert echo.kwargs == {"parse_mode": "HTML"}
    assert agent_calls == [{"content": "Add milk & eggs", "history_text": "🎙 Add milk & eggs"}]


def test_voice_empty_transcript(agent_calls, monkeypatch):
    monkeypatch.setattr(voice, "is_available", lambda: True)
    monkeypatch.setattr(voice, "transcribe", AsyncMock(return_value=""))
    update = _update(voice=SimpleNamespace(file_size=10, get_file=_file(b"ogg")))
    asyncio.run(main.handle_voice(update, MagicMock()))
    assert "couldn't make out" in update.message.reply_text.await_args.args[0]
    assert agent_calls == []


def test_voice_unavailable_and_oversized(agent_calls, monkeypatch):
    monkeypatch.setattr(voice, "is_available", lambda: False)
    update = _update(voice=SimpleNamespace(file_size=10, get_file=_file(b"")))
    asyncio.run(main.handle_voice(update, MagicMock()))
    assert "aren't available" in update.message.reply_text.await_args.args[0]

    monkeypatch.setattr(voice, "is_available", lambda: True)
    big = SimpleNamespace(file_size=MAX_UPLOAD_BYTES * 2, get_file=_file(b""))
    update = _update(voice=big)
    asyncio.run(main.handle_voice(update, MagicMock()))
    assert "under 10 MB" in update.message.reply_text.await_args.args[0]
    big.get_file.assert_not_awaited()
    assert agent_calls == []


def test_strangers_are_ignored(agent_calls, monkeypatch):
    update = _update(photo=[SimpleNamespace(file_size=10, get_file=_file(_jpeg()))], caption=None)
    update.effective_user.id = 999
    asyncio.run(main.handle_photo(update, MagicMock()))
    update.message.reply_text.assert_not_awaited()
    assert agent_calls == []
