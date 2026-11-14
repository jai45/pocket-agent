"""Tests for voice transcription with a fake Whisper model (no download)."""

import asyncio
from types import SimpleNamespace

import pytest

from bot.media import voice


class FakeWhisper:
    def __init__(self, segments):
        self.segments = segments
        self.received = None

    def transcribe(self, audio, **kwargs):
        self.received = audio.read()
        info = SimpleNamespace(language="en", duration=2.5)
        return (SimpleNamespace(text=t) for t in self.segments), info


@pytest.fixture(autouse=True)
def no_model():
    voice.set_model(None)
    yield
    voice.set_model(None)


def test_segments_are_joined_and_trimmed():
    fake = FakeWhisper([" Remind me to call mum", " at six. "])
    voice.set_model(fake)
    assert asyncio.run(voice.transcribe(b"ogg-bytes")) == "Remind me to call mum at six."
    assert fake.received == b"ogg-bytes"


def test_silence_gives_empty_string():
    voice.set_model(FakeWhisper([]))
    assert asyncio.run(voice.transcribe(b"x")) == ""


def test_unavailable_model():
    assert voice.is_available() is False
    with pytest.raises(RuntimeError):
        asyncio.run(voice.transcribe(b"x"))


def test_load_failure_keeps_bot_running(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert voice.load_model() is False
    assert voice.is_available() is False
