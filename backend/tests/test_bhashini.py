"""Bhashini Dhruva client + honest-degradation rules.

No network: the HTTP layer is stubbed. What is under test:

* disabled-by-default → ``ServiceDisabled`` (product stays English-only)
* the Dhruva pipeline v2 payload shape (``pipelineTasks`` list + ``inputData``)
* same-language requests never call the service (no fabricated round-trips)
* malformed provider responses raise instead of inventing text
"""

from __future__ import annotations

import pytest

from app.services.bhashini import (
    BhashiniClient,
    BhashiniError,
    ServiceDisabled,
    SpeechService,
    TextToSpeechService,
    TranslationService,
)
from tests.conftest import run


class _StubResponse:
    def __init__(self, body):
        self.status_code = 200
        self._body = body
        self.text = ""

    def json(self):
        return self._body


class _StubAsyncClient:
    """Records exactly what BhashiniClient POSTs, returns a canned body."""

    body: dict = {}
    calls: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        _StubAsyncClient.calls.append({"url": url, "payload": json, "headers": headers})
        return _StubResponse(_StubAsyncClient.body)


@pytest.fixture()
def stub_http(monkeypatch):
    _StubAsyncClient.calls = []
    monkeypatch.setattr("app.services.bhashini.httpx.AsyncClient", _StubAsyncClient)
    return _StubAsyncClient


def _client() -> BhashiniClient:
    return BhashiniClient(api_key="test-key", pipeline_url="https://dhruva.test/run")


# ------------------------------------------------------------ disabled path
def test_disabled_without_configuration():
    service = TranslationService(client=None, service_id=None)
    assert service.enabled is False
    with pytest.raises(ServiceDisabled):
        run(service.translate("vanakkam", source="ta", target="en"))


def test_disabled_with_client_but_no_service_id():
    service = TextToSpeechService(client=_client(), service_id=None)
    assert service.enabled is False
    with pytest.raises(ServiceDisabled):
        run(service.synthesize("hello", language="en"))


# ------------------------------------------------------------ payload shape
def test_translate_payload_matches_dhruva_v2(stub_http):
    stub_http.body = {"pipelineResponse": [{"taskType": "translation", "output": [{"target": "where is the zone"}]}]}
    service = TranslationService(client=_client(), service_id="ai4b/nmt-ta-en")

    result = run(service.translate("மீன்", source="ta", target="en"))

    assert result.text == "where is the zone"
    call = stub_http.calls[0]
    tasks = call["payload"]["pipelineTasks"]
    assert isinstance(tasks, list) and len(tasks) == 1  # services pass [task], not a bare dict
    task = tasks[0]
    assert task["taskType"] == "translation"
    assert task["config"]["language"] == {"sourceLanguage": "ta", "targetLanguage": "en"}
    assert task["config"]["serviceId"] == "ai4b/nmt-ta-en"
    assert call["payload"]["inputData"] == {"input": [{"source": "மீன்"}]}
    assert call["headers"]["Authorization"] == "test-key"


def test_asr_payload_uses_audio_content(stub_http):
    stub_http.body = {"pipelineResponse": [{"taskType": "asr", "output": [{"target": "zone 20 km"}]}]}
    service = SpeechService(client=_client(), service_id="ai4b/asr-ta")

    result = run(service.transcribe("UklGRiQ=", source_language="ta"))

    assert result.text == "zone 20 km"
    payload = stub_http.calls[0]["payload"]
    assert payload["inputData"] == {"audio": [{"audioContent": "UklGRiQ="}]}
    assert payload["pipelineTasks"][0]["taskType"] == "asr"


def test_same_language_never_calls_the_service(stub_http):
    """en→en must echo, not round-trip through an MT model."""
    service = TranslationService(client=_client(), service_id="ai4b/nmt-ta-en")
    result = run(service.translate("exactly this", source="en", target="en-US"))
    assert result.text == "exactly this"
    assert stub_http.calls == []


# ------------------------------------------------------ malformed responses
def test_missing_output_raises_instead_of_inventing(stub_http):
    stub_http.body = {"pipelineResponse": [{"taskType": "translation", "output": []}]}
    service = TranslationService(client=_client(), service_id="svc")
    with pytest.raises(BhashiniError):
        run(service.translate("x", source="ta", target="en"))


def test_missing_pipeline_response_raises(stub_http):
    stub_http.body = {"status": "success"}  # no pipelineResponse[] at all
    service = TranslationService(client=_client(), service_id="svc")
    with pytest.raises(BhashiniError):
        run(service.translate("x", source="ta", target="en"))


def test_invalid_base64_audio_rejected(stub_http):
    service = SpeechService(client=_client(), service_id="svc")
    with pytest.raises(BhashiniError):
        run(service.transcribe("!!!not base64!!!", source_language="ta"))
    assert stub_http.calls == []
