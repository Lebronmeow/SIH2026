"""Central ORCA configuration.

All configuration is environment-driven (``ORCA_`` prefix) via pydantic-settings.
Dataset IDs are **never** hardcoded in Python source — they live in
``backend/app/config/datasets.json`` (overridable with ``ORCA_DATASETS_CONFIG``).
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config/settings.py -> config -> app -> backend -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


class DataMode(str, Enum):
    """Where scientific values come from.

    ``DEMO`` serves cached/curated data packs and the UI *must* display a
    "DEMO / CACHED DATA" banner. ``LIVE`` fetches from configured providers.
    """

    LIVE = "live"
    DEMO = "demo"


class LLMProvider(str, Enum):
    """Reasoning-layer provider. ``NONE`` = fully deterministic pipeline."""

    NONE = "none"
    OPENAI = "openai"
    AZURE = "azure"
    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai-compatible"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ORCA_",
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------ app
    app_name: str = "ORCA"
    debug: bool = False
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"]
    )

    # ------------------------------------------------------------- data mode
    data_mode: DataMode = DataMode.DEMO
    data_dir: Path = REPO_ROOT / "data"
    demo_dir: Path = REPO_ROOT / "data" / "demo"
    cache_dir: Path = REPO_ROOT / "data" / "cache"
    cache_ttl_hours: float = 6.0

    # Boundaries / restricted-area layer directory (GeoJSON/GeoPackage files).
    boundaries_dir: Path = REPO_ROOT / "data" / "demo" / "boundaries"

    # Coastal exclusion band: candidate zones closer than this to the land
    # polygons are pre-excluded. Shoreline datasets disagree by 1-3 km near
    # complicated coasts, and no small craft fishes in the surf — the band
    # keeps recommendations in genuinely open water. Metres.
    coastal_exclusion_band_m: float = 1500.0

    # Validated pilot region (bounding box, degrees): the area where boundary
    # layers, shorelines and data coverage are verified. Queries with an
    # origin OUTSIDE this box still run, but every response carries an
    # explicit caution so nobody mistakes an unvalidated area for a covered
    # one. Defaults to the Rameswaram / Palk Bay / Gulf of Mannar pack.
    supported_region_south: float = 6.3
    supported_region_west: float = 77.5
    supported_region_north: float = 10.7
    supported_region_east: float = 81.6
    supported_region_name: str = "Palk Bay & Gulf of Mannar"

    # ------------------------------------------------------------ datasets
    datasets_config: Path = REPO_ROOT / "backend" / "app" / "config" / "datasets.json"
    erddap_servers_config: Path = (
        REPO_ROOT / "backend" / "app" / "config" / "erddap_servers.json"
    )

    # ------------------------------------------------------------ database
    database_url: str = "sqlite:///./orca.db"

    # ------------------------------------------------------------------ LLM
    llm_provider: LLMProvider = LLMProvider.NONE
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_timeout_seconds: float = 45.0

    # -------------------------------------------------------------- Bhashini
    # Voice/NMT is OPTIONAL: without a key the product stays English-only and
    # the UI hides the mic. serviceIds are per-tenant model picks from the
    # ULCA/Dhruva catalog — configuration, never Python literals.
    bhashini_enabled: bool = False
    bhashini_api_key: str | None = None
    bhashini_pipeline_url: str = (
        "https://dhruva-api.bhashini.gov.in/services/pipeline/v2/run"
    )
    bhashini_asr_service_id: str | None = None
    bhashini_nmt_service_id: str | None = None
    bhashini_tts_service_id: str | None = None
    bhashini_timeout_seconds: float = 30.0

    # -------------------------------------------------------- local voice
    # Keyless speech fallback (app/services/local_voice.py). `local_asr_model`
    # is any faster-whisper size: tiny/base/small (small = best Indian-language
    # accuracy; downloaded once from Hugging Face on first use).
    local_asr_model: str = "small"

    # ------------------------------------------------------------- providers
    protected_planet_api_key: str | None = None
    open_meteo_base_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_marine_base_url: str = "https://marine-api.open-meteo.com/v1/marine"

    @property
    def llm_enabled(self) -> bool:
        """True when a reasoning layer is configured AND has credentials."""
        if self.llm_provider == LLMProvider.NONE:
            return False
        return bool(self.llm_api_key)

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.cache_dir):
            Path(p).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
