import { Marker, Tooltip } from 'react-leaflet';
import L from 'leaflet';

const PIN = (n) => `
<svg viewBox="0 0 28 38" width="28" height="38" xmlns="http://www.w3.org/2000/svg">
  <path d="M14 1C7 1 2 6.3 2 13c0 9 12 24 12 24s12-15 12-24C26 6.3 21 1 14 1z" fill="#dc2626" stroke="#fff" stroke-width="2"/>
  <circle cx="14" cy="13" r="6" fill="#fff"/>
  <text x="14" y="16.5" text-anchor="middle" font-size="9" font-weight="700" fill="#dc2626" font-family="system-ui">${n}</text>
</svg>`;

export default function StopMarker({ lat, lng, name, index }) {
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  const icon = L.divIcon({
    className: 'stop-icon',
    html: PIN(index + 1),
    iconSize: [28, 38], iconAnchor: [14, 37],
  });
  return (
    <Marker position={[lat, lng]} icon={icon}>
      {name && <Tooltip direction="top" offset={[0, -34]}>{name}</Tooltip>}
    </Marker>
  );
}
