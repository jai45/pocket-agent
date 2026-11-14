"""Voice notes: local speech-to-text with faster-whisper.

Transcribing locally means audio never leaves this machine and costs
nothing per minute. The model takes a few seconds to load, so we load it
once at startup and reuse it.
"""

import asyncio
import io
import logging
from typing import Protocol

logger = logging.getLogger(__name__)

MODEL_SIZE = "base"


class Transcriber(Protocol):
    def transcribe(self, audio, **kwargs): ...


# Set by load_model() at startup; stays None if loading failed.
_model: Transcriber | None = None


def load_model() -> bool:
    """Load Whisper once. First run downloads ~150 MB; later runs use the cache.

    Returns False (and keeps the bot running) if it can't load, e.g. offline
    on the very first run; voice notes then get a friendly "not available".
    """
    global _model
    try:
        from faster_whisper import WhisperModel  # heavy import, only when needed

        # int8 on CPU: much less memory, barely less accurate for speech.
        _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    except Exception:  # noqa: BLE001 - voice is optional; text chat must still work
        logger.exception("Could not load the Whisper model; voice notes disabled")
        _model = None
        return False
    logger.info("Whisper '%s' model loaded", MODEL_SIZE)
    return True


def set_model(model: Transcriber | None) -> None:
    """Swap the model (tests use a fake)."""
    global _model
    _model = model


def is_available() -> bool:
    return _model is not None


def _transcribe_sync(audio: bytes) -> str:
    # transcribe() returns a lazy generator; the work happens while we join it.
    segments, info = _model.transcribe(io.BytesIO(audio), beam_size=5)
    text = " ".join(s.text.strip() for s in segments).strip()
    logger.info("voice_transcribed language=%s seconds=%.1f chars=%d",
                getattr(info, "language", "?"), getattr(info, "duration", 0.0), len(text))
    return text


async def transcribe(audio: bytes) -> str:
    """Speech -> text in a worker thread.

    Whisper is CPU-heavy for a second or more; running it on the event loop
    would freeze the bot (no replies, no reminders) until it finished.
    """
    if _model is None:
        raise RuntimeError("voice model not loaded")
    return await asyncio.to_thread(_transcribe_sync, audio)
