FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# No apt libraries needed: the science-stack manylinux wheels are
# self-contained — netCDF4 vendors HDF5/netCDF/curl, shapely vendors GEOS,
# pyproj vendors PROJ (see the *.libs dirs inside each wheel).

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
