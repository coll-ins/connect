import { TileLayer } from 'react-leaflet';

const KEY = import.meta.env.VITE_CARTO_KEY;

const CARTO = {
  url: `https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png?key=${KEY}`,
  subdomains: 'abcd',
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
};

const OSM = {
  url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  subdomains: 'abc',
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
};

export default function BaseTileLayer() {
  const src = KEY ? CARTO : OSM;
  return (
    <TileLayer
      url={src.url}
      subdomains={src.subdomains}
      attribution={src.attribution}
      maxZoom={19}
      keepBuffer={6}
      updateWhenZooming={false}
    />
  );
}
