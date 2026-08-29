"""Fetch a high-fidelity land mask (Natural Earth 10m) for the safety engine.

The original demo pack carried a hand-drawn "coarse demo mask" that missed
real land near Rameswaram (a 20 km-west recommendation landed on Mandapam).
Natural Earth 10m admin-0 is **public domain** (no license restriction) and
resolves coastlines far better than the coarse mask, so it is safe to use as
the hard-constraint land layer in every data mode.

Writes ``data/demo/rams/boundaries/land_mask_natural_earth_10m.geojson`` and
appends attribution. Re-run any time to refresh:

    cd backend && .venv/Scripts/python -X utf8 scripts/fetch_land_mask.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_admin_0_countries.geojson"
)
COUNTRIES = {"IND": "India", "LKA": "Sri Lanka"}
OUT = Path(__file__).resolve().parents[2] / "data" / "demo" / "rams" / "boundaries"
ATTRIBUTION = OUT / "ATTRIBUTION.md"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"downloading Natural Earth 10m admin-0 countries ...")
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        r = client.get(SOURCE_URL)
        r.raise_for_status()
        world = r.json()

    features = []
    for f in world["features"]:
        props = f.get("properties", {})
        iso = props.get("ISO_A3") or props.get("ADM0_A3") or ""
        if iso in COUNTRIES:
            features.append({
                "type": "Feature",
                "properties": {
                    "id": f"land-{iso.lower()}",
                    "name": f"{COUNTRIES[iso]} (Natural Earth 10m coastline)",
                    "kind": "land",
                    "authority": "reference",
                    "hard_constraint": True,
                    "source_id": "natural-earth-10m-admin-0",
                    "license": "Public domain",
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                },
                "geometry": f["geometry"],
            })

    if len(features) != len(COUNTRIES):
        print(f"ERROR: expected {len(COUNTRIES)} countries, matched {[f['properties']['id'] for f in features]}")
        return 1

    out_file = OUT / "land_mask_natural_earth_10m.geojson"
    out_file.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )
    size_mb = out_file.stat().st_size / 1e6
    print(f"wrote {out_file} ({size_mb:.1f} MB, {len(features)} features)")

    note = (
        "\nNatural Earth 10m admin-0 country polygons (India, Sri Lanka):\n"
        "Made with Natural Earth — public domain, no restrictions.\n"
        "https://www.naturalearthdata.com/downloads/10m-cultural-vectors/\n"
        f"Retrieved {datetime.now(timezone.utc).isoformat()} by scripts/fetch_land_mask.py\n"
    )
    existing = ATTRIBUTION.read_text(encoding="utf-8") if ATTRIBUTION.exists() else ""
    if "Natural Earth" not in existing:
        ATTRIBUTION.write_text(existing + note, encoding="utf-8")
        print(f"updated {ATTRIBUTION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
