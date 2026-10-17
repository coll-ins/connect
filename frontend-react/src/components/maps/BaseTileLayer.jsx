import { TileLayer } from 'react-leaflet';

if (typeof navigator !== 'undefined' && 'serviceWorker' in navigator) {
  navigator.serviceWorker
    .register(`${import.meta.env.BASE_URL}tile-sw.js`)
    .catch(() => {});
}

export default function BaseTileLayer() {
  return (
    <TileLayer
      url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      maxZoom={19}
      keepBuffer={6}
      updateWhenZooming={false}
    />
  );
}
