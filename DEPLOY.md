# Deploying ORCA for team testing

Frontend on **Vercel**, backend on **Render** (free tier for both).
Total setup ≈ 10 minutes; no secrets required for the default
deterministic pipeline (live ERDDAP/Open-Meteo data, no LLM).

## 1. Push the repo to GitHub

```bash
git remote add origin https://github.com/Lebronmeow/SIH2026.git
git push -u origin main
```

## 2. Backend on Render

1. Render dashboard → **New +** → **Blueprint** → select `Lebronmeow/SIH2026`.
2. Render reads [render.yaml](render.yaml): a Docker web service
   `orca-backend` on the free plan (spins down after 15 min idle — first
   request after idle takes ~1 min).
3. Once built, note the service URL — Render picks a suffix, e.g.
   `https://orca-backend-whvh.onrender.com`.
   Verify: open `https://<render-url>/api/system/status` → JSON with `"mode":"live"`.

Free-tier note: the stack (numpy/xarray/netCDF4) is memory-hungry; if the
free instance OOMs on cold start, scale to Starter ($7/mo) — for team testing
free is usually enough.

## 3. Frontend on Vercel

1. Vercel → **Add New…** → **Project** → import `Lebronmeow/SIH2026`.
2. **Root Directory: `frontend`** (framework auto-detects Vite).
3. Env vars: none required — `frontend/vercel.json` proxies `/api/*` to
   `https://orca-backend-whvh.onrender.com/api/*` (same-origin, no CORS needed).
   **If your Render URL differs, edit that one line in
   [frontend/vercel.json](frontend/vercel.json).**
4. Deploy → note the URL, e.g. `https://orca-sih2026.vercel.app`.
5. If you route via `VITE_API_BASE` instead of the proxy: set
   `VITE_API_BASE=https://<render-url>` at build and update
   `ORCA_CORS_ORIGINS` on Render to include your vercel.app origin
   (JSON list, e.g. `["https://orca-sih2026.vercel.app"]`).

## 4. Team test checklist

- Open the Vercel URL → no demo banner (live mode).
- Ask: *"Where is the safest and most productive fishing zone 20 km off
  Rameswaram tomorrow morning?"*
- Zones on the map sit in open water; the yellow start dot sits on the water
  launch point; the route avoids Rameswaram island.
- Map pane renders on phones (map → query → recommendation stack).
- First request after the backend idles may take ~1 min (Render free tier).
