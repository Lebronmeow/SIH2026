"""Deterministic query parser — the LLM-free path must handle the demo
query shapes: distance (single + range), relative IST time windows, objectives
and place resolution (builtin gazetteer, no network)."""

from __future__ import annotations

from datetime import timedelta

from app.agents.query_parser import DeterministicQueryParser, QueryParsingError
from tests.conftest import run

PARSER = DeterministicQueryParser()


def test_distance_single_value():
    parsed = run(PARSER.parse("safest zone 20 km off Rameswaram"))
    assert parsed.distance_km == 20.0


def test_distance_range_takes_midpoint():
    parsed = run(PARSER.parse("productive zone 10 to 15 km off Rameswaram"))
    assert parsed.distance_range_km == (10.0, 15.0)
    assert parsed.distance_km == 12.5


def test_tomorrow_morning_is_ist_window():
    """'tomorrow morning' resolves to 05:00-11:00 IST (= UTC+5:30)."""
    parsed = run(PARSER.parse("zone 20 km off Rameswaram tomorrow morning"))
    window = parsed.time_window
    assert window is not None
    assert window.end - window.start == timedelta(hours=6)
    # window expressed in UTC; IST offset must be honoured (5:30 ahead)
    assert (window.start + timedelta(hours=5, minutes=30)).hour == 5


def test_no_time_words_means_pipeline_default():
    parsed = run(PARSER.parse("safest zone 20 km off Rameswaram"))
    assert parsed.time_window is None


def test_place_phrase_stops_at_time_words():
    """'off Rameswaram tomorrow morning' must resolve Rameswaram, not the
    whole sentence fragment, as the place."""
    parsed = run(PARSER.parse("zone 20 km off Rameswaram tomorrow morning"))
    assert parsed.origin is not None
    assert parsed.origin.place.strip().lower() == "rameswaram"


def test_objectives_extracted():
    parsed = run(PARSER.parse("safest and most productive zone near Rameswaram"))
    assert "low_risk" in parsed.objectives
    assert "high_productivity" in parsed.objectives


def test_unknown_place_is_none_not_invented():
    """No network, no gazetteer hit → origin stays None. The parser must NOT
    guess coordinates (the workflow then asks the user for a named port)."""
    parsed = run(PARSER.parse("zone 20 km off Middle Of Nowhere tomorrow morning"))
    assert parsed.origin is None


def test_empty_query_rejected():
    try:
        run(PARSER.parse("   "))
    except QueryParsingError:
        pass
    else:  # pragma: no cover
        raise AssertionError("empty query must raise QueryParsingError")
