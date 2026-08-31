"""Query Understanding — deterministic parser + optional LLM refinement.

The deterministic parser handles the canonical demo query shapes (distance,
place, relative time, objectives) without any API key. When an LLM is
configured, the LLM version extracts the same :class:`ParsedQuery` schema via
structured output; BOTH go through the same validation and the same place
resolver, and neither is allowed to invent coordinates.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from app.agents.explainer import TIMEZONE_OFFSET
from app.services.place_resolver import PlaceResolver
from app.schemas.recommendation import Origin, ParsedQuery, TimeWindow

_DISTANCE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(km|kms|kilometer|kilometres|kilometer|kilometres|kilometers)\b", re.IGNORECASE)
_RANGE_RE = re.compile(r"(\d+)\s*(?:-|to|–)\s*(\d+)\s*km", re.IGNORECASE)
_TIME_WORDS = ("morning", "afternoon", "evening", "night", "dawn", "dusk")

_OBJECTIVE_MAP = {
    "safe": "low_risk",
    "safety": "low_risk",
    "shelter": "low_risk",
    "productive": "high_productivity",
    "production": "high_productivity",
    "fish": "high_productivity",
    "catch": "high_productivity",
    "pfz": "high_productivity",
}

# words that end a place phrase in "off/near <place> <rest of sentence>"
_PLACE_STOPWORDS = {
    "tomorrow", "today", "tonight", "morning", "afternoon", "evening",
    "night", "dawn", "dusk", "day", "please", "and", "with", "for",
    "where", "which", "what", "between", "within",
}


class QueryParsingError(ValueError):
    pass


class DeterministicQueryParser:
    """Regex/keyword parser — zero dependencies on external services."""

    def __init__(self, resolver: PlaceResolver | None = None) -> None:
        self.resolver = resolver or PlaceResolver()

    async def parse(self, text: str) -> ParsedQuery:
        text = (text or "").strip()
        if not text:
            raise QueryParsingError("empty query")
        parsed = ParsedQuery(raw_text=text)

        # ---- distance (range wins over single value)
        rng = _RANGE_RE.search(text)
        dist = _DISTANCE_RE.search(text)
        if rng:
            lo, hi = float(rng.group(1)), float(rng.group(2))
            parsed.distance_range_km = (min(lo, hi), max(lo, hi))
            parsed.distance_km = round((lo + hi) / 2.0, 2)
        elif dist:
            parsed.distance_km = float(dist.group(1).replace(",", "."))

        # ---- time window
        parsed.time_window = self._time_window(text)

        # ---- objectives
        low = text.lower()
        for word, objective in _OBJECTIVE_MAP.items():
            if word in low and objective not in parsed.objectives:
                parsed.objectives.append(objective)

        # ---- origin place
        parsed.origin = await self._place(text)
        return parsed

    @staticmethod
    def _time_window(text: str) -> TimeWindow | None:
        low = text.lower()
        now = datetime.now(timezone.utc)
        day_offset = 0
        if "tomorrow" in low:
            day_offset = 1
        elif "day after" in low:
            day_offset = 2
        elif "today" in low or "tonight" in low:
            day_offset = 0
        else:
            return None  # no explicit relative time -> workflow default applies

        start_hour, end_hour = 5, 11  # default dawn-to-late-morning
        if "afternoon" in low:
            start_hour, end_hour = 12, 17
        elif "evening" in low or "dusk" in low or "night" in low:
            start_hour, end_hour = 17, 21
        elif "dawn" in low or "early" in low:
            start_hour, end_hour = 4, 8

        # interpret in IST (UTC+5:30) then convert to UTC
        base = (now + timedelta(days=day_offset)).astimezone(timezone(timedelta(hours=TIMEZONE_OFFSET)))
        start = base.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        end = base.replace(hour=end_hour, minute=0, second=0, microsecond=0)
        return TimeWindow(start=start.astimezone(timezone.utc), end=end.astimezone(timezone.utc))

    async def _place(self, text: str) -> Origin | None:
        # explicit patterns first: "off/near/from <place>"; stop the capture at
        # the first time/qualifier word so we don't resolve "X Tomorrow Morning"
        m = re.search(r"\b(?:off|near|from|around|close to)\s+([A-Za-z][A-Za-z ]{2,30})", text, re.IGNORECASE)
        candidates: list[str] = []
        if m:
            words: list[str] = []
            for word in m.group(1).split():
                if word.lower() in _PLACE_STOPWORDS:
                    break
                words.append(word)
            trimmed = " ".join(words).strip(" .,?!")
            if trimmed:
                candidates.append(trimmed)
        # then any known port name present anywhere in the text
        from app.services.place_resolver import _BUILTIN_PORTS

        low = text.lower()
        candidates += [name for name in _BUILTIN_PORTS if name in low]
        for candidate in candidates:
            origin = await self.resolver.resolve(candidate)
            if origin:
                return origin
        return None


class LLMQueryParser:
    """LLM-backed parser (used only when ORCA_LLM_* is configured).

    Implemented against the OpenAI-compatible chat-completions API with a
    strict JSON schema so it works with OpenAI, Azure OpenAI, OpenRouter,
    Ollama, vLLM etc. The model may only CHOOSE places/attributes; coordinates
    still come from the PlaceResolver, never from the model.
    """

    def __init__(self, api_key: str, model: str, base_url: str | None, fallback: DeterministicQueryParser) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.fallback = fallback

    async def parse(self, text: str) -> ParsedQuery:
        import httpx

        system = (
            "You extract structured parameters from a fisherman's query. "
            "Return ONLY JSON with keys: intent, distance_km (number|null), place (string|null), "
            "when (one of 'today','tomorrow','day_after',null), part_of_day (one of 'dawn','morning','afternoon','evening','night',null), "
            "objectives (array from: high_productivity, low_risk), notes. "
            "Never invent coordinates. Never add facts that are not in the query."
        )
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}],
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                url = (self.base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
                r = await client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
            import json

            data = json.loads(content)
        except Exception:  # noqa: BLE001 — LLM unavailable: fall back, never fail
            return await self.fallback.parse(text)

        # the model may legally return null for any key (it was told it may)
        # — never let a null intent crash ParsedQuery validation
        parsed = ParsedQuery(raw_text=text, intent=data.get("intent") or "find_safe_productive_zone")
        if data.get("distance_km") is not None:
            try:
                parsed.distance_km = float(data["distance_km"])
            except (TypeError, ValueError):
                pass
        if data.get("when"):
            parser = DeterministicQueryParser(self.fallback.resolver)
            pseudo = f"{data['when'].replace('_', ' ')} {data.get('part_of_day') or ''}"
            parsed.time_window = parser._time_window(pseudo)
        parsed.objectives = [o for o in data.get("objectives", []) if o in ("high_productivity", "low_risk")] or parsed.objectives
        parsed.notes = data.get("notes")
        place = data.get("place")
        if place:
            parsed.origin = await self.fallback.resolver.resolve(place)
        if parsed.origin is None:
            parsed.origin = await self.fallback.resolver.resolve(text)
        return parsed
