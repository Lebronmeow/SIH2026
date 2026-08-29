"""Shared test fixtures.

Rules:
* **No network** — geocoding is monkeypatched off (builtin gazetteer only),
  providers are the demo pack (files only) or synthetic stubs.
* The committed demo pack (``data/demo/rams``) is real cached data; tests that
  need exact conditions build their own layers/fields instead.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services.place_resolver import PlaceResolver


@pytest.fixture(autouse=True)
def offline_geocoding(monkeypatch):
    """Force the builtin port gazetteer — tests must never hit the network."""

    async def _no_geocoding(self, name):
        return None

    monkeypatch.setattr(PlaceResolver, "_via_geocoding", _no_geocoding)


def run(coro):
    """Run an async call from sync tests (pytest-asyncio not a dependency)."""
    return asyncio.run(coro)


@pytest.fixture()
def backend_root() -> Path:
    return Path(__file__).resolve().parents[1]
