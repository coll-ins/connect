import { useEffect, useRef } from 'react';
import L from 'leaflet';
import { useMap } from 'react-leaflet';
import { snapToRoute, pointAt, headingAt } from './route';

const BUS_SVG = `
<svg viewBox="0 0 40 40" width="44" height="44" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="20" cy="22" rx="10" ry="16" fill="rgba(0,0,0,.28)"/>
  <rect x="11" y="3" width="18" height="34" rx="5" fill="#1d4ed8" stroke="#fff" stroke-width="1.6"/>
  <rect x="13.5" y="6" width="13" height="6" rx="1.5" fill="#bfdbfe"/>
  <rect x="13.5" y="14" width="13" height="14" rx="1.5" fill="#93c5fd"/>
  <rect x="13.5" y="30" width="13" height="4" rx="1.5" fill="#bfdbfe"/>
  <circle cx="14.5" cy="4.5" r="1.4" fill="#fde047"/><circle cx="25.5" cy="4.5" r="1.4" fill="#fde047"/>
</svg>`;

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

export default function BusMarker({ route, lat, lng }) {
  const map = useMap();
  const S = useRef({ marker: null, s: null, curS: null, from: 0, to: 0, t0: 0, dur: 4000, lastFixAt: 0, heading: 0, raf: 0, route: null });

  useEffect(() => {
    const st = S.current;
    const icon = L.divIcon({
      className: 'bus-icon',
      html: `<div class="bus-rot">${BUS_SVG}</div>`,
      iconSize: [44, 44], iconAnchor: [22, 22],
    });
    st.marker = L.marker([0, 0], { icon, zIndexOffset: 1000, opacity: 0 }).addTo(map);

    const frame = (now) => {
      if (st.route && st.route.pts.length > 1 && st.s != null) {
        const p = clamp((now - st.t0) / st.dur, 0, 1);
        const s = st.from + (st.to - st.from) * p;
        st.curS = s;
        st.marker.setLatLng(pointAt(st.route, s));
        const diff = ((headingAt(st.route, s) - st.heading + 540) % 360) - 180;
        st.heading = (st.heading + diff * 0.15 + 360) % 360;
        const el = st.marker.getElement()?.querySelector('.bus-rot');
        if (el) el.style.transform = `rotate(${st.heading}deg)`;
      }
      st.raf = requestAnimationFrame(frame);
    };
    st.raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(st.raf); st.marker.remove(); };
  }, [map]);

  useEffect(() => {
    const st = S.current;
    if (lat == null || lng == null || !st.marker) return;
    const now = performance.now();
    st.route = route;
    st.marker.setOpacity(1);

    if (!route || route.pts.length < 2) { st.marker.setLatLng([lat, lng]); return; }

    const cur = st.curS;
    let sn = cur != null ? snapToRoute(route, lat, lng, cur - 30, cur + 3000) : null;
    if (!sn || sn.dist > 80) sn = snapToRoute(route, lat, lng);
    if (!sn) return;

    if (st.s == null || sn.dist > 150) {
      st.from = st.to = sn.s; st.t0 = now; st.curS = sn.s; st.s = sn.s;
    } else {
      st.from = cur ?? sn.s;
      st.to = Math.max(sn.s, st.from);
      st.t0 = now;
      st.dur = clamp((now - (st.lastFixAt || now - 4000)) * 1.1, 2500, 9000);
      st.s = st.to;
    }
    st.lastFixAt = now;
  }, [lat, lng, route]);

  return null;
}
