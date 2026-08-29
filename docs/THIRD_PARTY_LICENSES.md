# Third-Party Licenses — ORCA

ORCA's own code is provided for the Smart India Hackathon without an open-source
license grant (hackathon deliverable). Everything below is used unmodified or
wrapped, with license compatibility verified **before** adoption.

## Runtime dependencies (backend)

| Package | Version | License | Use | Notes |
|---|---|---|---|---|
| fastapi | 0.138 | MIT | API framework | |
| uvicorn | latest | BSD-3 | ASGI server | |
| pydantic / pydantic-settings | 2.x | MIT | schemas/settings | |
| httpx | latest | BSD-3 | async HTTP (Open-Meteo, Bhashini, geocoding) | |
| erddapy | 3.3.0 | BSD-3-Clause | ERDDAP client | |
| xarray | 2026.7.0 | Apache-2.0 | gridded fields | |
| netCDF4 | latest | MIT | NetCDF IO (demo pack, ERDDAP) | |
| numpy | latest | BSD-3 | numerics | |
| scipy | latest | BSD-3 | ndimage (front detection) | |
| pandas | latest | BSD-3 | tables (Argo, AIS) | |
| geopandas | ≥1.1 | BSD-3 | boundary layers | |
| shapely | ≥2.0.4 | BSD-3 | geometry, prepared tests | |
| pyproj | ≥3.7 | MIT | geodesics, UTM transforms | |
| geojson-pydantic | latest | MIT | typed GeoJSON | |
| SQLAlchemy / GeoAlchemy2 | latest | MIT / LGPL-2.1 | optional PostGIS path (off by default) | GeoAlchemy2 is LGPL — only linked in the optional PostGIS deployment, not the default file-based path |
| pyais | ≥3.2.1 | MIT | AIS decoding | |
| agent-framework | 1.16.0 | MIT | workflow/agent orchestration | Microsoft Agent Framework |

## Runtime dependencies (frontend)

| Package | License | Use |
|---|---|---|
| maplibre-gl ^6.6.0 | BSD-3 | map engine |
| @vis.gl/react-maplibre ^8.1.0 | MIT | React bindings |
| deck.gl ^9.3.0 | MIT | data layers |
| @deck.gl/mapbox ^9.3.0 | MIT | MapboxOverlay bridge |
| react ^19 | MIT | UI |
| vite / @vitejs/plugin-react | MIT | build tool |

## Data sources & services

| Source | License / terms | How used | Redistribution stance |
|---|---|---|---|
| NOAA ERDDAP (coastwatch/PFEG, NWS) | Public domain (work of the U.S. Government) | SST, chlorophyll, currents, waves, wind | cached subsets in demo pack OK |
| INCOIS ERDDAP | Government of India open science server | Argo profiles; regional checks | cached subsets with attribution; `verify=False` for its incomplete TLS chain, logged |
| Open-Meteo (marine/weather/geocoding) | CC-BY 4.0 (attribution required), free non-commercial | wind/waves live, place resolution | attribution shown in UI + sources list |
| VLIZ Marine Regions (eez_boundaries, line_id 1306/1311) | CC-BY 4.0 · DOI 10.14284/632 | India–Sri Lanka IMBL geometry | cached with attribution file |
| WDPA / Protected Planet | free key; **no redistribution of geometry** | MPA checks at runtime with operator key | geometry NEVER committed or shipped |
| Bhashini (Dhruva) | GoI platform, per-app key | ASR/MT/TTS (optional) | no redistribution |
| OpenFreeMap tiles (liberty style) | free, no key | basemap | — |

## Reference-only (no code used)

- **SIMROUTE** — *no license* (all rights reserved). Concepts only; cited:
  Grifoll & Sotillo, *Ocean Engineering* 255:111427 (2022).
- **MIT-STARLab**, **MSP-Symphony** — design/paper reference.
- **Bhashini examples repo** (`bhashini-api-examples`, Apache-2.0) — API-shape
  reference.
- **agent-framework-samples** (MIT) — usage examples.

## Rejected on license grounds

- **pgRouting** — GPL-2.0: incompatible with ORCA's permissive composition and
  would force GPL/PostGIS into the default path. Replaced by ~350 lines of own
  A* code (`backend/app/engines/routing/`).
- **WDPA geometry redistribution** — technically permitted *use*, forbidden
  *redistribution*: handled by runtime fetch only.

## Attribution file in the demo pack

`data/demo/boundaries/ATTRIBUTION.md` (created by `scripts/fetch_demo_data.py`)
records the Marine Regions DOI/URL and retrieval date for the IMBL geometry, as
required by CC-BY 4.0.
