"""Local, keyless speech engine — the honest fallback for Bhashini.

When no ``ORCA_BHASHINI_API_KEY`` is configured, ORCA still needs real voice
input/output in multiple languages. This module provides it with two
well-known OSS packages (no API keys, no fabricated capability):

* **ASR** — ``faster-whisper`` (MIT, CTranslate2 port of OpenAI Whisper).
  Multilingual (en/hi/ta/te/ml/bn); runs fully offline after a one-time
  model download. Audio in *any* container the browser records (webm/opus,
  ogg/opus, wav) is decoded by the bundled PyAV — no ffmpeg install.
* **TTS** — ``edge-tts`` (MIT). Neural voices for Indian English, Hindi,
  Tamil, Telugu, Malayalam, Bengali and Gujarati via Microsoft's public
  neural voice endpoint (no key). Odia has no neural voice there — the
  request fails honestly rather than speaking Odia text with a Hindi voice.

Every failure raises :class:`LocalVoiceError`; nothing is ever invented.
"""

from __future__ import annotations

import base64
import binascii
import io
import logging
from dataclasses import dataclass

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

# Whisper language codes with an *approved* local model. Odia ("or") is not
# reliably supported by the small/base models — auto-detect would return some
# other language's text, which is worse than an honest refusal.
WHISPER_LANGUAGES = {"en", "hi", "ta", "te", "ml", "bn", "gu"}

# edge-tts neural voice per ORCA language code (checked against the
# `edge-tts --list-voices` catalog; en/hi/ta/te/ml/bn/gu all exist, or does not).
EDGE_VOICES: dict[str, str] = {
    "en": "en-IN-NeerjaNeural",
    "hi": "hi-IN-SwaraNeural",
    "ta": "ta-IN-PallaviNeural",
    "te": "te-IN-ShrutiNeural",
    "ml": "ml-IN-SobhanaNeural",
    "bn": "bn-IN-TanishaaNeural",
    "gu": "gu-IN-DhwaniNeural",
}


class LocalVoiceError(RuntimeError):
    """Any local ASR/TTS failure (missing package, model, audio, network)."""


@dataclass(frozen=True, slots=True)
class LocalTranscription:
    text: str
    language: str
    engine: str


@dataclass(frozen=True, slots=True)
class LocalSpeech:
    audio_base64: str
    language: str
    engine: str


class LocalVoiceEngine:
    """Lazy-loading wrapper: heavy imports/models only on first real use."""

    def __init__(self) -> None:
        self._whisper = None  # WhisperModel instance (lazy)

    # ------------------------------------------------------------------ ASR
    def asr_available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return True

    def _model(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel

            model_size = get_settings().local_asr_model
            logger.info("local ASR: loading faster-whisper model %r (CPU, int8)", model_size)
            self._whisper = WhisperModel(model_size, device="cpu", compute_type="int8")
        return self._whisper

    async def transcribe(self, audio_base64: str, language: str) -> LocalTranscription:
        if not self.asr_available():
            raise LocalVoiceError("local ASR unavailable: faster-whisper is not installed")
        try:
            audio = base64.b64decode(audio_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise LocalVoiceError("audio payload is not valid base64") from exc
        if len(audio) < 512:
            raise LocalVoiceError("audio payload too short to contain speech")

        lang = language.split("-")[0]
        whisper_lang: str | None = lang if lang in WHISPER_LANGUAGES else None
        model = self._model()
        import anyio

        def _run():
            segments, info = model.transcribe(
                io.BytesIO(audio),
                language=whisper_lang,
                beam_size=get_settings().local_asr_beam_size,
                # short one-shot queries: carrying context across segments
                # only invites repetition/hallucination loops
                condition_on_previous_text=False,
                vad_filter=True,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            return text, info

        try:
            text, info = await anyio.to_thread.run_sync(_run)
        except Exception as exc:  # decode/model errors — surfaced honestly
            raise LocalVoiceError(f"local ASR failed: {exc}") from exc
        if not text:
            raise LocalVoiceError("no speech recognized in the recording")
        return LocalTranscription(text=text, language=lang, engine=f"faster-whisper:{get_settings().local_asr_model}")

    # ------------------------------------------------------------------ TTS
    def tts_available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False
        return True

    def tts_language_supported(self, language: str) -> bool:
        return language.split("-")[0] in EDGE_VOICES

    async def synthesize(self, text: str, language: str) -> LocalSpeech:
        if not self.tts_available():
            raise LocalVoiceError("local TTS unavailable: edge-tts is not installed")
        lang = language.split("-")[0]
        voice = EDGE_VOICES.get(lang)
        if voice is None:
            raise LocalVoiceError(
                f"no neural voice available for language {lang!r} — try English/Hindi/Tamil/Telugu/Malayalam/Bengali"
            )
        import edge_tts

        try:
            communicate = edge_tts.Communicate(text, voice)
            chunks: list[bytes] = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
        except Exception as exc:
            raise LocalVoiceError(f"local TTS failed: {exc}") from exc
        audio = b"".join(chunks)
        if not audio:
            raise LocalVoiceError("local TTS produced no audio")
        return LocalSpeech(
            audio_base64=base64.b64encode(audio).decode("ascii"),
            language=lang,
            engine=f"edge-tts:{voice}",
        )


_engine: LocalVoiceEngine | None = None


def get_local_voice() -> LocalVoiceEngine:
    global _engine
    if _engine is None:
        _engine = LocalVoiceEngine()
    return _engine
