"""Shared test fixtures.

Rules:
* **No network** — geocoding is monkeypatched off (builtin gazetteer only),
  providers are the demo pack (files only) or synthetic stubs.
* The committed demo pack (``data/demo/rams``) is real cached data; tests that
  need exact conditions build their own layers/fields instead.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from app.config.settings import get_settings
from app.services.place_resolver import PlaceResolver

# Tests pin demo mode *before any Settings() can be constructed* — a developer's
# local .env may legitimately set ORCA_DATA_MODE=live, but the suite asserts
# demo-pack behavior and must never touch the network. Real env vars win over
# pydantic-settings' dotenv file, so this overrides the local .env.
os.environ["ORCA_DATA_MODE"] = "demo"


@pytest.fixture(autouse=True)
def demo_mode():
    """Drop the cached settings so every test rebuilds with the pinned env."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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
