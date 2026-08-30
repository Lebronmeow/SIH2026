# Attribution

India–Sri Lanka maritime boundary lines (WFS line_id 1306 and 1311) from:

Flanders Marine Institute (VLIZ) — Marine Regions, Maritime Boundaries Geodatabase.
https://www.marineregions.org/ · DOI 10.14284/632 · Licensed CC-BY 4.0.

Retrieved 2026-08-29T11:05:00.312118+00:00 by scripts/fetch_demo_data.py.

## Land mask (chart-grade shoreline)

`land_gshhg_full.geojson` — GSHHG v2.3.7 full-resolution land polygons (L1),
clipped to the pilot region (Palk Bay / Gulf of Mannar / Rameswaram / N Sri Lanka):

GSHHG — A Global Self-consistent, Hierarchical, High-resolution Geography Database.
Wessel, P., and W. H. F. Smith, 1996, "A global, self-consistent, hierarchical,
high-resolution shoreline database", J. Geophys. Res., 101, 8741-8743.
https://www.soest.hawaii.edu/pwessel/gshhg/ · Distributed under the GNU Lesser
General Public License (data derived from satellite and hydrographic sources).
Retrieved 2026-08-30 and clipped with scripts tools (bbox 77.5–81.6 E, 6.3–10.7 N).

Replaces the earlier Natural Earth 10m land mask: NE 10m carries ~2–3 km
positional error around complicated coasts (Rameswaram/Pamban), which made
in-water zone candidates read as on-land on the OSM basemap. GSHHG full
resolution is chart-grade (~100 m) and agrees with the basemap.

## Protected areas

`mpa_gulf_of_mannar.geojson` — Gulf of Mannar Marine National Park boundary as
mapped in OpenStreetMap (relation 415570, `boundary=national_park`,
`protect_class=2`): © OpenStreetMap contributors, ODbL 1.0,
https://www.openstreetmap.org/relation/415570 · Retrieved 2026-08-30.
REFERENCE ONLY — the legally definitive limit is the official notification by
the Tamil Nadu Forest Department / MoEFCC. Replaces an earlier hand-drawn
approximation hexagon (`demo_mpa_gulf_of_mannar.geojson`, removed).
