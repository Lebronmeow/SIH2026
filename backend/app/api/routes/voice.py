"""Voice / language API.

Two stacks, chosen per request — never mixed, never faked:

1. **Bhashini Dhruva** (preferred, when ``ORCA_BHASHINI_*`` is configured).
2. **Local keyless engine** (:mod:`app.services.local_voice`) — faster-whisper
   ASR (offline after one model download) + edge-tts neural voices.

All endpoints degrade *honestly*: when neither stack can serve a request the
caller gets 503 SERVICE_DISABLED (capability missing) or 502 SERVICE_ERROR
(a real upstream failure), with a machine-readable body. Status:

* ``GET  /api/voice/status``    → capability map for the UI
* ``POST /api/voice/transcribe`` → base64 audio → text (ASR)
* ``POST /api/translate``        → text → text (NMT; Bhashini only)
* ``POST /api/voice/speak``      → text → base64 audio (TTS)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config.settings import get_settings
from app.services.bhashini import (
    BhashiniError,
    ServiceDisabled,
    get_speech_service,
    get_translation_service,
    get_tts_service,
)
from app.services.local_voice import LocalVoiceError, get_local_voice

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["voice"])

_LANG = "^[a-z]{2}(-[A-Za-z]{2})?$"


def _err(code: str, status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _disabled(exc: Exception) -> HTTPException:
    if isinstance(exc, LocalVoiceError):
        return _err("SERVICE_ERROR", 502, str(exc))
    code = 503 if isinstance(exc, ServiceDisabled) else 502
    return _err(
        "SERVICE_DISABLED" if code == 503 else "SERVICE_ERROR",
        code,
        str(exc),
    )


async def _transcribe(audio_base64: str, language: str, encoding: str) -> tuple[str, str, str]:
    """Bhashini when configured, else the local engine. Returns (text, lang, engine)."""
    bhashini = get_speech_service()
    if bhashini.enabled:
        result = await bhashini.transcribe(audio_base64, language, encoding)
        return result.text, result.source_language, f"bhashini:{result.service_id}"
    local = get_local_voice()
    if local.asr_available():
        result = await local.transcribe(audio_base64, language)
        return result.text, result.language, result.engine
    raise ServiceDisabled(
        "transcription unavailable: Bhashini not configured and faster-whisper not installed"
    )


async def _synthesize(text: str, language: str) -> tuple[str, str, str, str]:
    """Bhashini when configured, else the local engine. Returns (audio_b64, lang, engine, fmt)."""
    tts = get_tts_service()
    if tts.enabled:
        result = await tts.synthesize(text, language)
        return result.audio_base64, result.language, f"bhashini:{result.service_id}", "wav"
    local = get_local_voice()
    if local.tts_available():
        result = await local.synthesize(text, language)
        return result.audio_base64, result.language, result.engine, "mp3"
    raise ServiceDisabled(
        "speech synthesis unavailable: Bhashini not configured and edge-tts not installed"
    )


@router.get("/voice/status")
async def voice_status() -> dict:
    """Capability map: the UI enables the mic / read-aloud only when true."""
    settings = get_settings()
    speech = get_speech_service()
    translation = get_translation_service()
    tts = get_tts_service()
    local = get_local_voice()
    bhashini_configured = settings.bhashini_enabled and bool(settings.bhashini_api_key)
    transcribe = speech.enabled or local.asr_available()
    speak = tts.enabled or local.tts_available()
    return {
        "configured": transcribe and speak,
        "engine": "bhashini" if bhashini_configured else ("local" if (transcribe or speak) else "none"),
        "transcribe": transcribe,
        "translate": translation.enabled,
        "speak": speak,
        "english_only_fallback": not (transcribe and translation.enabled and speak),
        "message": (
            "Bhashini configured (Dhruva ASR / NMT / TTS)"
            if bhashini_configured
            else (
                f"Local voice ready — Whisper '{settings.local_asr_model}' speech recognition "
                "and neural read-aloud, no API key needed"
                if (transcribe and speak)
                else "No voice service available — install faster-whisper + edge-tts, or set ORCA_BHASHINI_*"
            )
        ),
    }


class TranscribeRequest(BaseModel):
    audio_base64: str = Field(min_length=32, max_length=20_000_000)
    language: str = Field(default="ta", pattern=_LANG)
    encoding: str = Field(default="wav", pattern="^(wav|mp3|flac|ogg)$")


@router.post("/voice/transcribe")
async def voice_transcribe(req: TranscribeRequest) -> dict:
    try:
        text, language, engine = await _transcribe(req.audio_base64, req.language, req.encoding)
    except BhashiniError as exc:
        raise _disabled(exc) from exc
    except LocalVoiceError as exc:
        raise _disabled(exc) from exc
    return {"text": text, "language": language, "service_id": engine}


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    source: str = Field(default="en", pattern=_LANG)
    target: str = Field(default="ta", pattern=_LANG)


@router.post("/translate")
async def translate(req: TranslateRequest) -> dict:
    try:
        result = await get_translation_service().translate(req.text, source=req.source, target=req.target)
    except BhashiniError as exc:
        raise _disabled(exc) from exc
    return {
        "text": result.text,
        "source": result.source_language,
        "target": result.target_language,
        "service_id": result.service_id,
    }


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: str = Field(default="ta", pattern=_LANG)


@router.post("/voice/speak")
async def voice_speak(req: SpeakRequest) -> dict:
    try:
        audio_base64, language, engine, fmt = await _synthesize(req.text, req.language)
    except BhashiniError as exc:
        raise _disabled(exc) from exc
    except LocalVoiceError as exc:
        raise _disabled(exc) from exc
    return {
        "audio_base64": audio_base64,
        "language": language,
        "service_id": engine,
        "format": fmt,
    }
