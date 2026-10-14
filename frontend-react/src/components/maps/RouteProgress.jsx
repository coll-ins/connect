import { Polyline } from 'react-leaflet';

export default function RouteProgress({
  split,
  weight = 8,
  color = '#9aa3b2',
  opacity = 0.9,
}) {
  if (!split || split.passed.length < 2) return null;

  return (
    <Polyline
      positions={split.passed}
      pathOptions={{
        color,
        weight,
        opacity,
        lineCap: 'round',
        lineJoin: 'round',
      }}
      interactive={false}
    />
  );
}
