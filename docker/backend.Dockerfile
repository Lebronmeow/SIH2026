FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# geospatial wheels (shapely/pyproj) ship binary wheels; only netCDF needs lib deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        libhdf5-0 libnetcdf19 libcurl4 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]>=3.2"

COPY backend/app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
