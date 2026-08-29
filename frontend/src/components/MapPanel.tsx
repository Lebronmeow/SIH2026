/**
 * Map panel: MapLibre base + deck.gl overlay with ORCA's evidence layers.
 * Layers (all from the backend, nothing hand-drawn):
 *   - boundary GeoJSON (IMBL line / MPA polygons / land) with authority badges
 *   - candidate zones (Scatterplot), recommended zone highlighted
 *   - safe route (PathLayer)
 */

import { useMemo } from "react";
import Map, { useControl } from "@vis.gl/react-maplibre";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// maplibre-gl v6 loads its tile/glyph worker relative to import.meta.url; under
// Vite's dep optimizer that sibling file is never emitted (404) and the map
// silently never renders — no tiles, no error. Point it at the real asset.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
maplibregl.setWorkerUrl(maplibreWorkerUrl);
import { MapboxOverlay } from "@deck.gl/mapbox";
import { ScatterplotLayer, PathLayer, GeoJsonLayer } from "@deck.gl/layers";
import type { PickingInfo } from "@deck.gl/core";
import type { AdvisoryResponse } from "../types";

const INITIAL_VIEW = {
  longitude: 79.31,
  latitude: 9.29,
  zoom: 8.6,
};

// colors
const ZONE_COLOR = [56, 189, 248, 220]; // sky
const RECOMMENDED_COLOR = [45, 212, 191, 255]; // teal accent
const ROUTE_COLOR = [45, 212, 191, 255];

export default function MapPanel(props: {
  response: AdvisoryResponse | null;
  onPickZone: (id: string | null) => void;
  selectedZoneId: string | null;
}) {
  const { response, selectedZoneId } = props;

  const scatters = useMemo(() => {
    const zones = response?.zones.filter((z) => !z.excluded) ?? [];
    const recommendedId = response?.recommended?.candidate.id;
    return zones.map((z) => ({
      position: [z.candidate.lon, z.candidate.lat] as [number, number],
      radius: z.candidate.id === recommendedId ? 900 : 550,
      color:
        z.candidate.id === recommendedId
          ? RECOMMENDED_COLOR
          : z.candidate.id === selectedZoneId
            ? [250, 204, 21, 255]
            : ZONE_COLOR,
      zone: z,
    }));
  }, [response, selectedZoneId]);

  const routePath = useMemo(() => {
    const r = response?.route;
    if (!r || r.coords.length < 2) return [];
    return [{ path: r.coords, mode: r.mode, dist: r.distance_km }];
  }, [response]);

  const boundaries = useMemo(() => response?.map_layers ?? [], [response]);

  const layers = useMemo(
    () => [
      // land polygons first (below everything)
      new GeoJsonLayer({
        id: "land",
        data: boundaries.filter((f) => f.properties?.kind === "land") as never,
        filled: true,
        stroked: true,
        getFillColor: [148, 163, 184, 60] as never,
        getLineColor: [148, 163, 184, 140] as never,
        lineWidthMinPixels: 1,
        pickable: false,
      }),
      new GeoJsonLayer({
        id: "mpa",
        data: boundaries.filter((f) => f.properties?.kind === "mpa" || f.properties?.kind === "restricted") as never,
        filled: true,
        stroked: true,
        getFillColor: [239, 68, 68, 40] as never,
        getLineColor: [239, 68, 68, 220] as never,
        lineWidthMinPixels: 2,
        pickable: true,
      }),
      new GeoJsonLayer({
        id: "imbl",
        data: boundaries.filter((f) => f.properties?.kind === "imbl") as never,
        filled: false,
        stroked: true,
        getLineColor: [239, 68, 68, 255] as never,
        getLineWidth: 3,
        lineWidthMinPixels: 3,
        pickable: true,
      }),
      new PathLayer({
        id: "route",
        data: routePath as never,
        getPath: (d: { path: [number, number][] }) => d.path,
        getColor: ROUTE_COLOR as never,
        getWidth: 4,
        widthMinPixels: 3,
        pickable: false,
      }),
      new ScatterplotLayer({
        id: "zones",
        data: scatters as never,
        getPosition: (d: { position: [number, number] }) => d.position,
        getRadius: (d: { radius: number }) => d.radius,
        getFillColor: (d: { color: number[] }) => d.color as never,
        radiusUnits: "meters" as never,
        radiusMinPixels: 6,
        stroked: true,
        getLineColor: [230, 239, 247, 220] as never,
        lineWidthMinPixels: 1,
        pickable: true,
        onClick: (info: PickingInfo) => {
          const zone = (info.object as { zone?: { candidate: { id: string } } } | null)?.zone;
          props.onPickZone(zone?.candidate.id ?? null);
          return true;
        },
      }),
    ],
    [boundaries, routePath, scatters, props],
  );

  return (
    <main className="map-container">
      <Map
        initialViewState={INITIAL_VIEW}
        mapStyle="https://tiles.openfreemap.org/styles/liberty"
      >
        <DeckGLBridge layers={layers} />
      </Map>
      <div className="map-legend">
        <span><i className="dot recommended" /> best zone</span>
        <span><i className="dot zone" /> other zones (tap)</span>
        <span><i className="dot route" /> safe route</span>
        <span><i className="line imbl" /> India–Sri Lanka boundary</span>
        <span><i className="poly mpa" /> protected area</span>
      </div>
      {response?.insufficient && (
        <div className="map-overlay-error">
          Unable to make a reliable recommendation with the currently available data.
        </div>
      )}
    </main>
  );
}

/** Bridge: deck.gl layers rendered into the MapLibre WebGL context. */
function DeckGLBridge(props: { layers: unknown[] }) {
  const overlay = useControl<MapboxOverlay>(
    () => new MapboxOverlay({ layers: props.layers as never }),
  );
  // keep the overlay's layers in sync across renders (useControl builds once)
  overlay?.setProps({ layers: props.layers as never });
  return null;
}
