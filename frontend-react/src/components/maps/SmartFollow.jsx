import { useEffect, useRef } from 'react';
import { useMap } from 'react-leaflet';
import { haversine, speedToZoom, toLatLng } from './wazeNav';

const MIN_ZOOM = 13;
const MAX_ZOOM = 18;
const MANUAL_HOLD_MS = 10000;
const clampZoom = (zoom) =>
  Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));

export default function SmartFollow({
  enabled = true,
  position,
  autoZoom = true,
  nextStageM = null,
}) {
  const map = useMap();
  const state = useRef({
    manualUntil: 0,
    programmatic: false,
    lastZoomAt: 0,
    sample: null,
    speedKmh: 0,
    manual: false,
  });
  const positionRef = useRef(null);
  const optionsRef = useRef(null);
  const settingsRef = useRef({ autoZoom, nextStageM });

  const normalized = toLatLng(position);
  const latitude = normalized?.[0];
  const longitude = normalized?.[1];

  useEffect(() => {
    if (!enabled) return undefined;

    const handlers = [
      map.touchZoom,
      map.scrollWheelZoom,
      map.doubleClickZoom,
      map.boxZoom,
      map.keyboard,
    ];
    optionsRef.current = {
      handlers: handlers.map((handler) => ({
        handler,
        enabled: handler?.enabled(),
      })),
      dragging: map.dragging?.enabled(),
    };

    map.dragging?.disable();
    handlers.forEach((handler, index) => {
      if (index < 3) handler?.enable();
      else handler?.disable();
    });

    return () => {
      const previous = optionsRef.current;
      if (!previous) return;

      previous.handlers.forEach(({ handler, enabled: wasEnabled }) => {
        if (!handler) return;
        if (wasEnabled) handler.enable();
        else handler.disable();
      });
      if (previous.dragging) map.dragging?.enable();
      else map.dragging?.disable();
    };
  }, [enabled, map]);

  useEffect(() => {
    positionRef.current = normalized;
    settingsRef.current = { autoZoom, nextStageM };
  }, [normalized, autoZoom, nextStageM]);

  useEffect(() => {
    if (!enabled) return undefined;

    let manualTimer;
    const announce = (manual) => {
      if (state.current.manual === manual) return;
      state.current.manual = manual;
      window.dispatchEvent(
        new CustomEvent('connect-map-manual', { detail: manual }),
      );
    };
    const holdAutoZoom = () => {
      state.current.manualUntil = Date.now() + MANUAL_HOLD_MS;
      announce(true);
      window.clearTimeout(manualTimer);
      manualTimer = window.setTimeout(() => {
        state.current.manualUntil = 0;
        announce(false);
        zoomToTarget();
      }, MANUAL_HOLD_MS);
    };
    const zoomToTarget = () => {
      const settings = settingsRef.current;
      if (!settings.autoZoom) return;

      const target = clampZoom(
        speedToZoom(state.current.speedKmh, settings.nextStageM),
      );
      if (Math.abs(target - map.getZoom()) <= 0.25) return;

      state.current.programmatic = true;
      state.current.lastZoomAt = Date.now();
      map.setZoom(target, { animate: true });
    };
    const onZoomStart = () => {
      if (state.current.programmatic) return;
      holdAutoZoom();
    };
    const onZoomEnd = () => {
      state.current.programmatic = false;
    };
    const onButtonZoom = (event) => {
      holdAutoZoom();
      const target = clampZoom(
        map.getZoom() + (Number(event.detail?.delta) || 0),
      );
      if (target === map.getZoom()) return;
      state.current.programmatic = true;
      map.setZoom(target, { animate: true });
    };
    const onRecenter = () => {
      window.clearTimeout(manualTimer);
      state.current.manualUntil = 0;
      state.current.lastZoomAt = 0;
      announce(false);
      if (positionRef.current) {
        map.panTo(positionRef.current, { animate: false });
      }
      zoomToTarget();
    };

    map.on('zoomstart', onZoomStart);
    map.on('zoomend', onZoomEnd);
    window.addEventListener('connect-map-zoom', onButtonZoom);
    window.addEventListener('connect-map-recenter', onRecenter);

    return () => {
      map.off('zoomstart', onZoomStart);
      map.off('zoomend', onZoomEnd);
      window.removeEventListener('connect-map-zoom', onButtonZoom);
      window.removeEventListener('connect-map-recenter', onRecenter);
      window.clearTimeout(manualTimer);
    };
  }, [enabled, map]);

  useEffect(() => {
    if (!enabled || latitude == null || longitude == null) return;

    const now = Date.now();
    const current = state.current;
    map.panTo([latitude, longitude], { animate: false });

    if (!current.sample) {
      current.sample = { position: [latitude, longitude], time: now };
    }

    const elapsed = (now - current.sample.time) / 1000;
    if (elapsed >= 0.8) {
      const instantaneous =
        (haversine(current.sample.position, [latitude, longitude]) /
          elapsed) *
        3.6;
      current.speedKmh =
        current.speedKmh * 0.7 + instantaneous * 0.3;
      current.sample = {
        position: [latitude, longitude],
        time: now,
      };
    }

    if (
      !autoZoom ||
      now < current.manualUntil ||
      now - current.lastZoomAt < 3000
    ) {
      return;
    }

    const target = clampZoom(speedToZoom(current.speedKmh, nextStageM));
    if (Math.abs(target - map.getZoom()) > 0.25) {
      current.programmatic = true;
      current.lastZoomAt = now;
      map.setZoom(target, { animate: true });
    }
  }, [
    enabled,
    map,
    latitude,
    longitude,
    autoZoom,
    nextStageM,
  ]);

  return null;
}
