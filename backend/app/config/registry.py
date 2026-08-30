"""DataSourceRegistry — the single source of truth for *who* ORCA gets data from.

Every provenance record emitted by ORCA references a ``SourceId`` registered
here. The registry separates three concerns:

1. **Identity** — stable id, display name, operating organisation.
2. **Legal/authority status** — license of the data, and whether the served
   geometry is *authoritative/legal* or a *reference* GIS product. This matters:
   an EEZ line from a GIS aggregator is NOT a legally binding maritime boundary.
3. **Transport** — base URL / endpoint used at runtime.

Dataset IDs (which specific ERDDAP dataset, etc.) are *not* stored here; they
live in ``datasets.json`` so they can be swapped without code changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Final


class Authority(str, Enum):
    """Legal standing of data served by a source."""

    AUTHORITATIVE = "authoritative"  # legal/instrument-backed (e.g. IMBL coordinates in a treaty annex)
    REFERENCE = "reference"  # best-effort GIS product, not legally definitive
    DESCRIPTIVE = "descriptive"  # scientific measurements / forecasts


class AccessKind(str, Enum):
    OPEN = "open"  # no key required
    REGISTRATION = "registration"  # free key after registration
    CREDENTIALS = "credentials"  # requires account/key


@dataclass(frozen=True, slots=True)
class DataSource:
    id: str
    name: str
    organization: str
    homepage: str
    access: AccessKind
    authority: Authority
    license: str | None = None  # fill from verified research; None = unverified
    license_verified: bool = False
    base_url: str | None = None
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


_SOURCES: Final[tuple[DataSource, ...]] = (
    # ---------------------------------------------------------- ocean science
    DataSource(
        id="incois-erddap",
        name="INCOIS ERDDAP",
        organization="Indian National Centre for Ocean Information Services, MoES, Govt. of India",
        homepage="https://erddap.incois.gov.in/erddap/index.html",
        access=AccessKind.OPEN,
        authority=Authority.DESCRIPTIVE,
        base_url="https://erddap.incois.gov.in/erddap",
        notes=(
            "National in-situ data (e.g. Indian_ARGO_Floats tabledap — verified live). NOTE: gridded "
            "holdings are archival; server presents an incomplete TLS chain (provider sets verify=False). "
            "PFZ advisories are portal images/PDF, not machine-readable."
        ),
        tags=("ocean", "insitu", "india"),
    ),
    DataSource(
        id="erddap-noaa",
        name="NOAA CoastWatch/PFEL ERDDAP",
        organization="NOAA",
        homepage="https://coastwatch.pfeg.noaa.gov/erddap/index.html",
        access=AccessKind.OPEN,
        authority=Authority.DESCRIPTIVE,
        license="Public domain (work of the U.S. Government)",
        license_verified=True,
        base_url="https://coastwatch.pfeg.noaa.gov/erddap",
        notes=(
            "Verified live from the dev machine: jplMURSST41 (SST 0.01°, current), "
            "erdMH1chla1day_R2022NRT (Aqua MODIS chla 4 km), nesdisSSH1day (geostrophic currents, "
            "~5 mo lag → flagged STALE). CAVEAT: pfeg times out from the Render deployment egress "
            "(2026-08-30) — deployed variables were moved to erddap-noaa-nws / pacioos."
        ),
        tags=("ocean", "erddap", "sst", "chlorophyll"),
    ),
    DataSource(
        id="erddap-noaa-nws",
        name="NOAA CoastWatch National ERDDAP",
        organization="NOAA",
        homepage="https://coastwatch.noaa.gov/erddap/index.html",
        access=AccessKind.OPEN,
        authority=Authority.DESCRIPTIVE,
        license="Public domain (work of the U.S. Government)",
        license_verified=True,
        base_url="https://coastwatch.noaa.gov/erddap",
        notes=(
            "Verified live: noaacwBLENDEDNRTcurrentsDaily (0.25° blended NRT ocean currents, "
            "u_current/v_current, current to within ~2 days) and noaacwNPPN20VIIRSDINEOFDaily "
            "(chlor_a, gap-filled VIIRS 9 km daily — deployed primary chlorophyll). This host is "
            "reachable from both the dev machine and Render."
        ),
        tags=("ocean", "erddap", "currents"),
    ),
    DataSource(
        id="erddap-pacioos",
        name="PacIOOS ERDDAP",
        organization="University of Hawai‘i / NOAA IOOS",
        homepage="https://pae-paha.pacioos.hawaii.edu/erddap/index.html",
        access=AccessKind.OPEN,
        authority=Authority.DESCRIPTIVE,
        base_url="https://pae-paha.pacioos.hawaii.edu/erddap",
        notes=(
            "Verified live datasets: ww3_global (waves 0.5°, hourly +7d forecast), ncep_global "
            "(winds 3-hourly), dhw_5km (CRW SST/anomaly)."
        ),
        tags=("ocean", "erddap", "waves", "wind"),
    ),
    DataSource(
        id="open-meteo",
        name="Open-Meteo (marine & weather forecast API)",
        organization="Open-Meteo",
        homepage="https://open-meteo.com",
        access=AccessKind.OPEN,
        authority=Authority.DESCRIPTIVE,
        base_url="https://api.open-meteo.com",
        notes=(
            "Free non-commercial, no API key (verified live from Gulf of Mannar). Attribution to "
            "Open-Meteo/DWD required per their terms."
        ),
        tags=("weather", "waves", "wind"),
    ),
    # ---------------------------------------------------------- boundaries
    DataSource(
        id="marine-regions",
        name="Marine Regions (VLIZ maritime boundaries & gazetteer)",
        organization="Flanders Marine Institute (VLIZ)",
        homepage="https://www.marineregions.org",
        access=AccessKind.OPEN,
        authority=Authority.REFERENCE,
        base_url="https://www.marineregions.org",
        notes=(
            "Maritime Boundaries geodatabase (EEZ 12/24/200 nm). Reference GIS geometry — "
            "NOT a legally definitive representation of the India–Sri Lanka IMBL."
        ),
        tags=("boundary", "eez", "reference"),
    ),
    DataSource(
        id="protected-planet",
        name="Protected Planet / WDPA",
        organization="UNEP-WCMC & IUCN",
        homepage="https://www.protectedplanet.net",
        access=AccessKind.REGISTRATION,
        authority=Authority.REFERENCE,
        base_url="https://api.protectedplanet.net",
        notes="Marine protected areas. Polygons are reference GIS products; check WDPA terms.",
        tags=("mpa", "protected"),
    ),
    # ---------------------------------------------------------- voice / language
    DataSource(
        id="bhashini",
        name="Bhashini (Dhruva) language AI services",
        organization="MeitY / Digital India Bhashini Division",
        homepage="https://bhashini.gov.in",
        access=AccessKind.REGISTRATION,
        authority=Authority.DESCRIPTIVE,
        base_url="https://dhruva-api.bhashini.gov.in",
        notes="ASR / NMT / TTS for Indian languages. Optional; disabled without credentials.",
        tags=("voice", "nmt", "tts"),
    ),
)


class DataSourceRegistry:
    """Lookup helpers over the registered sources."""

    def __init__(self, sources: tuple[DataSource, ...] = _SOURCES) -> None:
        self._sources = {s.id: s for s in sources}

    def get(self, source_id: str) -> DataSource:
        try:
            return self._sources[source_id]
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"Unknown data source id: {source_id!r}") from exc

    def all(self) -> list[DataSource]:
        return list(self._sources.values())

    def to_public_json(self) -> list[dict[str, object]]:
        """Serializable form for API responses (safe to expose)."""
        return [
            {
                "id": s.id,
                "name": s.name,
                "organization": s.organization,
                "homepage": s.homepage,
                "access": s.access.value,
                "authority": s.authority.value,
                "license": s.license,
                "license_verified": s.license_verified,
                "notes": s.notes,
            }
            for s in self._sources.values()
        ]


registry = DataSourceRegistry()
