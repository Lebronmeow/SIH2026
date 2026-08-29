"""Voice / language API (Bhashini Dhruva, optional).

Phase 6 surface. All endpoints degrade *honestly*: without ORCA_BHASHINI_*
configuration they return 503 SERVICE_DISABLED with a machine-readable body so
the UI can hide the mic and fall back to English-only text input. Status:

* ``GET  /api/voice/status``    → capability map for the UI
* ``POST /api/voice/transcribe`` → base64 audio → text (ASR)
* ``POST /api/translate``        → text → text (NMT)
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["voice"])

_LANG = "^[a-z]{2}(-[A-Za-z]{2})?$"


def _disabled(exc: BhashiniError) -> HTTPException:
    code = 503 if isinstance(exc, ServiceDisabled) else 502
    return HTTPException(status_code=code, detail={"code": "SERVICE_DISABLED" if code == 503 else "SERVICE_ERROR", "message": str(exc)})


@router.get("/voice/status")
async def voice_status() -> dict:
    """Capability map: the UI enables the mic / language picker only when true."""
    settings = get_settings()
    speech = get_speech_service()
    translation = get_translation_service()
    tts = get_tts_service()
    return {
        "configured": settings.bhashini_enabled and bool(settings.bhashini_api_key),
        "transcribe": speech.enabled,
        "translate": translation.enabled,
        "speak": tts.enabled,
        "english_only_fallback": not (speech.enabled and translation.enabled and tts.enabled),
        "message": (
            "Bhashini configured"
            if settings.bhashini_enabled and settings.bhashini_api_key
            else "Bhashini not configured — English-only mode (set ORCA_BHASHINI_* to enable)"
        ),
    }


class TranscribeRequest(BaseModel):
    audio_base64: str = Field(min_length=32, max_length=20_000_000)
    language: str = Field(default="ta", pattern=_LANG)
    encoding: str = Field(default="wav", pattern="^(wav|mp3|flac|ogg)$")


@router.post("/voice/transcribe")
async def voice_transcribe(req: TranscribeRequest) -> dict:
    try:
        result = await get_speech_service().transcribe(req.audio_base64, req.language, req.encoding)
    except BhashiniError as exc:
        raise _disabled(exc) from exc
    return {
        "text": result.text,
        "language": result.source_language,
        "service_id": result.service_id,
    }


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
        result = await get_tts_service().synthesize(req.text, req.language)
    except BhashiniError as exc:
        raise _disabled(exc) from exc
    return {
        "audio_base64": result.audio_base64,
        "language": result.language,
        "service_id": result.service_id,
    }
