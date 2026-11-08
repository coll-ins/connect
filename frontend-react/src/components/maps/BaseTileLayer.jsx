import { useCallback, useEffect, useState } from 'react';
import { Pane, TileLayer, useMap } from 'react-leaflet';
import { webglOk } from './webgl';

const KEY = import.meta.env.VITE_CARTO_KEY;
const TRAFFIC_KEY = import.meta.env.VITE_TOMTOM_KEY;

export const LIVE_TRAFFIC = Boolean(TRAFFIC_KEY);

const CARTO = {
  url: `https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png?key=${KEY}`,
  subdomains: 'abcd',
  attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
};
const OSM = {
  url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  subdomains: 'abc',
  attribution: '&copy; OpenStreetMap contributors',
};

// Free, keyless vector map (openfreemap.org, commercial use allowed). Positron is
// the minimal grey style closest to ride-hailing maps.
const VECTOR_STYLE = 'https://tiles.openfreemap.org/styles/positron';
const VECTOR_ATTRIBUTION =
  '<a href="https://openfreemap.org" target="_blank">OpenFreeMap</a> &copy; <a href="https://www.openmaptiles.org/" target="_blank">OpenMapTiles</a> &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>';
const VECTOR_TIMEOUT_MS = 8000;

// TomTom free tier: 50k tiles/day, no card. Over quota the tiles just stop loading.
const TRAFFIC_URL = `https://api.tomtom.com/traffic/map/4/tile/flow/relative0/{z}/{x}/{y}.png?key=${TRAFFIC_KEY}`;

function VectorBaseLayer({ onReady }) {
  const map = useMap();

  useEffect(() => {
    let layer = null;
    let cancelled = false;
    let timer = null;

    const drop = (reason) => {
      if (cancelled) return;
      console.warn('[map] vector basemap unavailable, using raster tiles:', reason);
      cancelled = true;
      clearTimeout(timer);
      layer?.remove();
      layer = null;
    };

    Promise.all([
      import('@maplibre/maplibre-gl-leaflet'),
      import('maplibre-gl'),
      import('maplibre-gl/dist/maplibre-gl-worker.mjs?url'),
      import('maplibre-gl/dist/maplibre-gl.css'),
    ])
      .then(([{ default: maplibreGL }, { setWorkerUrl }, { default: workerUrl }]) => {
        if (cancelled) return;
        // MapLibre finds its worker next to its own file, which bundling breaks.
        setWorkerUrl(workerUrl);
        layer = maplibreGL({
          style: VECTOR_STYLE,
          attributionControl: { customAttribution: VECTOR_ATTRIBUTION },
        }).addTo(map);
        const gl = layer.getMaplibreMap();
        timer = setTimeout(() => drop('timeout'), VECTOR_TIMEOUT_MS);
        gl.once('load', () => {
          if (cancelled) return;
          clearTimeout(timer);
          onReady();
        });
        gl.on('error', (event) => {
          if (!gl.loaded()) drop(event?.error?.message || 'style error');
        });
      })
      .catch((error) => drop(error?.message || error));

    return () => {
      cancelled = true;
      clearTimeout(timer);
      layer?.remove();
    };
  }, [map, onReady]);

  return null;
}

// Traffic is shown only this close to the bus, where it matters to the trip.
export const TRAFFIC_RADIUS_M = 1000;

/* Clip the traffic pane to a circle around `center` ([lat, lng]). */
function TrafficNear({ center }) {
  const map = useMap();
  const lat = center?.[0];
  const lng = center?.[1];

  useEffect(() => {
    const pane = map.getPane('traffic');
    if (!pane) return undefined;
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
      pane.style.clipPath = 'circle(0px at 0px 0px)';
      return undefined;
    }
    // Panes share the map pane's layer coordinates, so this follows panning.
    const clip = () => {
      const at = map.latLngToLayerPoint([lat, lng]);
      const edge = map.latLngToLayerPoint([lat + TRAFFIC_RADIUS_M / 111320, lng]);
      const radius = Math.abs(at.y - edge.y);
      pane.style.clipPath = `circle(${radius}px at ${at.x}px ${at.y}px)`;
    };
    clip();
    map.on('zoomend viewreset', clip);
    return () => {
      map.off('zoomend viewreset', clip);
    };
  }, [map, lat, lng]);

  return null;
}

export default function BaseTileLayer({ traffic = false, trafficAround }) {
  const [vectorReady, setVectorReady] = useState(false);
  const markReady = useCallback(() => setVectorReady(true), []);
  const src = KEY ? CARTO : OSM;

  return (
    <>
      {webglOk && <VectorBaseLayer onReady={markReady} />}
      {!vectorReady && (
        <TileLayer
          url={src.url}
          subdomains={src.subdomains}
          attribution={src.attribution}
          maxZoom={19}
          keepBuffer={6}
          updateWhenZooming={false}
        />
      )}
      {traffic && LIVE_TRAFFIC && (
        <Pane name="traffic" style={{ zIndex: 350 }}>
          <TileLayer
            url={TRAFFIC_URL}
            attribution="Traffic &copy; TomTom"
            opacity={0.85}
            maxZoom={19}
            minZoom={10}
          />
          {trafficAround !== undefined && <TrafficNear center={trafficAround} />}
        </Pane>
      )}
    </>
  );
}
