"""In-memory response store for retrieved recommendations.

Prototype-scoped: advisory responses are kept in a bounded LRU keyed by
request_id so the frontend can re-open a past recommendation (GET
/api/recommendations/{id}) without re-running the pipeline. No persistence
is implied; a restart clears it — which is honest for a demo.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from app.schemas.recommendation import RecommendationResponse

_MAX_ENTRIES = 64
_TTL = timedelta(hours=6)


class ResponseStore:
    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        self._entries: OrderedDict[str, RecommendationResponse] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_entries

    def put(self, response: RecommendationResponse) -> None:
        with self._lock:
            self._entries[response.request_id] = response
            self._entries.move_to_end(response.request_id)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)

    def get(self, request_id: str) -> RecommendationResponse | None:
        with self._lock:
            resp = self._entries.get(request_id)
            return resp


_store: ResponseStore | None = None


def get_store() -> ResponseStore:
    global _store
    if _store is None:
        _store = ResponseStore()
    return _store
