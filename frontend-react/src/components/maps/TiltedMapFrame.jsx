import { useEffect, useRef } from 'react';
import { useMap } from 'react-leaflet';
import './TiltedMapFrame.css';

const TILT_DEFAULT = false;

const flatRequested =
  typeof window !== 'undefined' &&
  new URLSearchParams(window.location.search).get('flat') === '1';

export const MAP_TILT_ENABLED = TILT_DEFAULT && !flatRequested;
export const MAP_TILT_ZOOM = 17;

export default function TiltedMapFrame({
  enabled = MAP_TILT_ENABLED,
  heading = 0,
  children,
}) {
  const stageRef = useRef(null);
  const headingRef = useRef(0);

  useEffect(() => {
    if (!enabled || !Number.isFinite(heading)) return;

    const previous = headingRef.current;
    const diff = ((heading - previous + 540) % 360) - 180;
    const next = previous + diff * 0.6;
    headingRef.current = next;

    const stage = stageRef.current;
    if (!stage) return;
    stage.style.setProperty('--map-heading', `${-next}deg`);
    stage.style.setProperty('--map-unrotate', `${next}deg`);
  }, [enabled, heading]);

  if (!enabled) return children;

  return (
    <div className="tilt-viewport">
      <div ref={stageRef} className="tilt-stage">
        {children}
      </div>
    </div>
  );
}

export function TiltFollow({
  enabled = MAP_TILT_ENABLED,
  position,
  zoom = MAP_TILT_ZOOM,
}) {
  const map = useMap();
  const startedRef = useRef(false);
  const lat = position?.[0];
  const lng = position?.[1];

  useEffect(() => {
    if (!enabled) return undefined;

    const handlers = [
      map.dragging,
      map.touchZoom,
      map.scrollWheelZoom,
      map.doubleClickZoom,
      map.boxZoom,
      map.keyboard,
    ];
    handlers.forEach((handler) => handler?.disable());

    return () => handlers.forEach((handler) => handler?.enable());
  }, [enabled, map]);

  useEffect(() => {
    if (!enabled || !Number.isFinite(lat) || !Number.isFinite(lng)) return;

    if (!startedRef.current) {
      startedRef.current = true;
      map.setView([lat, lng], zoom, { animate: false });
      return;
    }

    map.panTo([lat, lng], {
      animate: true,
      duration: 1.2,
      easeLinearity: 1,
      noMoveStart: true,
    });
  }, [enabled, map, lat, lng, zoom]);

  return null;
}
