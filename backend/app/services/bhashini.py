"""Bhashini Dhruva pipeline client — optional speech/translation services.

Phase 6. Bhashini (MeitY) provides ASR / NMT / TTS for Indian languages via
the Dhruva pipeline API (studied via ``bhashini-api-examples``, Apache-2.0 →
verdict B; see OPEN_SOURCE_RESEARCH.md). One POST to the pipeline endpoint
carries ``pipelineTasks`` (each with its ``serviceId``) plus ``inputData``;
the response echoes one ``pipelineResponse`` entry per task.

Rules this module enforces:

* **Disabled by default.** Without ``ORCA_BHASHINI_API_KEY`` every service is
  inert and callers get :class:`ServiceDisabled` — the product falls back to
  English-only UI, never to a fake translation.
* **serviceIds are configuration** (``ORCA_BHASHINI_*_SERVICE_ID``) — the ULCA
  catalog assigns per-tenant model ids; we never guess one in code.
* **No fabrication.** A failed call raises; a missing ``output`` block raises;
  callers surface "translation unavailable" rather than passing through
  invented text.
"""

from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass

import httpx

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class BhashiniError(RuntimeError):
    """Any Dhruva pipeline failure (transport, auth, malformed response)."""


class ServiceDisabled(BhashiniError):
    """Bhashini not configured (no API key / no serviceId for the task)."""


@dataclass(frozen=True, slots=True)
class TranslationResult:
    text: str
    source_language: str
    target_language: str
    service_id: str | None = None


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    source_language: str
    service_id: str | None = None


@dataclass(frozen=True, slots=True)
class SpeechResult:
    audio_base64: str
    language: str
    service_id: str | None = None


class BhashiniClient:
    """Thin async HTTP wrapper over one Dhruva pipeline endpoint."""

    def __init__(self, api_key: str, pipeline_url: str, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._url = pipeline_url
        self._timeout = timeout

    async def run_pipeline(self, tasks: list[dict], input_data: dict) -> list[dict]:
        """POST one pipeline request; return the ``pipelineResponse`` entries.

        ``tasks``: [{"taskType": ..., "config": {"language": {...}, "serviceId": ...}}]
        ``input_data``: {"input": [{"source": ...}], "audio": [{"audioContent": ...}]}
        """
        payload = {"pipelineTasks": tasks, "inputData": input_data}
        headers = {
            "Authorization": self._api_key,
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise BhashiniError(f"Dhruva pipeline unreachable: {exc}") from exc
        if resp.status_code == 401:
            raise BhashiniError("Dhruva pipeline rejected the API key (401)")
        if resp.status_code >= 400:
            raise BhashiniError(f"Dhruva pipeline error {resp.status_code}: {resp.text[:200]}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise BhashiniError("Dhruva pipeline returned non-JSON body") from exc
        responses = body.get("pipelineResponse")
        if not isinstance(responses, list):
            raise BhashiniError("Dhruva pipeline response missing pipelineResponse[]")
        return responses


def _first_output(responses: list[dict], task_type: str) -> dict:
    for entry in responses:
        if entry.get("taskType") == task_type:
            outputs = entry.get("output") or []
            if outputs:
                return outputs[0]
            raise BhashiniError(f"Dhruva {task_type} task returned no output")
    raise BhashiniError(f"Dhruva response missing {task_type} task")


class TranslationService:
    """Text → text (NMT). ``enabled`` only when key + serviceId are set."""

    def __init__(self, client: BhashiniClient | None, service_id: str | None) -> None:
        self._client = client
        self._service_id = service_id

    @property
    def enabled(self) -> bool:
        return self._client is not None and bool(self._service_id)

    async def translate(self, text: str, source: str, target: str) -> TranslationResult:
        src = source.split("-")[0]
        tgt = target.split("-")[0]
        if src == tgt:
            return TranslationResult(text=text, source_language=src, target_language=tgt)
        if not self.enabled:
            raise ServiceDisabled("translation unavailable: Bhashini not configured")
        task = {
            "taskType": "translation",
            "config": {
                "language": {"sourceLanguage": src, "targetLanguage": tgt},
                "serviceId": self._service_id,
            },
        }
        responses = await self._client.run_pipeline([task], {"input": [{"source": text}]})
        out = _first_output(responses, "translation")
        translated = out.get("target")
        if not translated:
            raise BhashiniError("translation output missing 'target'")
        return TranslationResult(text=translated, source_language=src, target_language=tgt,
                                 service_id=self._service_id)


class SpeechService:
    """ASR: base64 audio → text. Config-driven serviceId."""

    def __init__(self, client: BhashiniClient | None, service_id: str | None) -> None:
        self._client = client
        self._service_id = service_id

    @property
    def enabled(self) -> bool:
        return self._client is not None and bool(self._service_id)

    async def transcribe(self, audio_base64: str, source_language: str,
                         encoding: str = "wav") -> TranscriptionResult:
        if not self.enabled:
            raise ServiceDisabled("transcription unavailable: Bhashini not configured")
        src = source_language.split("-")[0]
        try:
            base64.b64decode(audio_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise BhashiniError("audio payload is not valid base64") from exc
        task = {
            "taskType": "asr",
            "config": {
                "language": {"sourceLanguage": src},
                "serviceId": self._service_id,
                "audioFormat": encoding,
            },
        }
        responses = await self._client.run_pipeline(
            [task], {"audio": [{"audioContent": audio_base64}]}
        )
        out = _first_output(responses, "asr")
        text = out.get("target") or out.get("source") or ""
        if not text:
            raise BhashiniError("asr output produced empty text")
        return TranscriptionResult(text=text, source_language=src, service_id=self._service_id)


class TextToSpeechService:
    """TTS: text → base64 audio. Config-driven serviceId."""

    def __init__(self, client: BhashiniClient | None, service_id: str | None) -> None:
        self._client = client
        self._service_id = service_id

    @property
    def enabled(self) -> bool:
        return self._client is not None and bool(self._service_id)

    async def synthesize(self, text: str, language: str) -> SpeechResult:
        if not self.enabled:
            raise ServiceDisabled("speech synthesis unavailable: Bhashini not configured")
        lang = language.split("-")[0]
        task = {
            "taskType": "tts",
            "config": {
                "language": {"sourceLanguage": lang},
                "serviceId": self._service_id,
            },
        }
        responses = await self._client.run_pipeline([task], {"input": [{"source": text}]})
        out = _first_output(responses, "tts")
        audio = out.get("audioContent")
        if not audio:
            raise BhashiniError("tts output missing 'audioContent'")
        return SpeechResult(audio_base64=audio, language=lang, service_id=self._service_id)


# ------------------------------------------------------------------ factories
def _client() -> BhashiniClient | None:
    s = get_settings()
    if not (s.bhashini_enabled and s.bhashini_api_key):
        return None
    return BhashiniClient(s.bhashini_api_key, s.bhashini_pipeline_url, s.bhashini_timeout_seconds)


def get_translation_service() -> TranslationService:
    return TranslationService(_client(), get_settings().bhashini_nmt_service_id)


def get_speech_service() -> SpeechService:
    return SpeechService(_client(), get_settings().bhashini_asr_service_id)


def get_tts_service() -> TextToSpeechService:
    return TextToSpeechService(_client(), get_settings().bhashini_tts_service_id)
