import { Marker, Tooltip } from 'react-leaflet';
import L from 'leaflet';
import './StopMarker.css';

const COLORS = {
  default: ['#ff6b4a', '#c62d14'],
  first: ['#34d399', '#047857'],
  last: ['#60a5fa', '#1d4ed8'],
};
const PATH = 'M14 1C7 1 2 6.3 2 13c0 9 12 24 12 24s12-15 12-24C26 6.3 21 1 14 1z';

const pinSvg = (n, variant) => {
  const [c1, c2] = COLORS[variant] || COLORS.default;
  const id = `sp-${variant}`;
  return `
<svg viewBox="0 0 28 38" width="28" height="38" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="${c1}"/><stop offset="1" stop-color="${c2}"/>
    </linearGradient>
    <radialGradient id="${id}-hi" cx=".35" cy=".25" r=".6">
      <stop offset="0" stop-color="#fff" stop-opacity=".55"/>
      <stop offset="1" stop-color="#fff" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <path d="${PATH}" fill="url(#${id})" stroke="#fff" stroke-width="2"/>
  <path d="${PATH}" fill="url(#${id}-hi)"/>
  <circle cx="14" cy="13" r="6" fill="#fff"/>
  <text x="14" y="16.5" text-anchor="middle" font-size="9" font-weight="700" fill="${c2}" font-family="system-ui">${n}</text>
</svg>`;
};

const cache = new Map();
export const stopIcon = (n, variant = 'default') => {
  const key = `${n}:${variant}`;
  if (!cache.has(key)) {
    cache.set(key, L.divIcon({
      className: 'stop-icon',
      html: pinSvg(n, variant),
      iconSize: [28, 38], iconAnchor: [14, 37],
    }));
  }
  return cache.get(key);
};

export default function StopMarker({ lat, lng, name, index, total }) {
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  const variant = index === 0 ? 'first' : total && index === total - 1 ? 'last' : 'default';
  return (
    <Marker position={[lat, lng]} icon={stopIcon(index + 1, variant)}>
      {name && <Tooltip direction="top" offset={[0, -34]}>{name}</Tooltip>}
    </Marker>
  );
}
