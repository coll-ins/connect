import { TileLayer } from 'react-leaflet';

export default function BaseTileLayer() {
  return (
    <TileLayer
      url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png"
      subdomains="abcd"
      maxZoom={19}
      keepBuffer={6}
      updateWhenZooming={false}
      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
    />
  );
}
