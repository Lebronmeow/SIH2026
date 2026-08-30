FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# geospatial wheels (shapely/pyproj) ship binary wheels; only netCDF needs lib deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        libhdf5-0 libnetcdf19 libcurl4 \
    && rm -rf /var/lib/apt/lists/*

# /srv IS the repo root: app/config/settings.py resolves REPO_ROOT as parents[3]
# (config -> app -> backend -> root), so boundaries and demo data land where the
# settings expect them — /srv/data/demo/...
WORKDIR /srv

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt "psycopg[binary]>=3.2"

COPY backend/app ./backend/app

# Demo pack (boundary layers load in EVERY mode; .nc/.json data enable demo mode)
COPY data/demo ./data/demo

# Render binds the container to $PORT; local runs default to 8000
EXPOSE 8000
CMD ["sh", "-c", "cd /srv/backend && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]