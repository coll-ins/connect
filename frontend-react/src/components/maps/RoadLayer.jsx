import { useMemo } from 'react';
import { buildRoute, snapStages } from './route';
import BusMarker from './BusMarker';
import StopMarker from './StopMarker';

// Must be rendered inside <MapContainer>. Pass geometry as stable references.
export default function RoadLayer({ geometry, stages, lat, lng }) {
  const route = useMemo(() => buildRoute(geometry), [geometry]);
  const snapped = useMemo(() => snapStages(route, stages), [route, stages]);
  return (
    <>
      <BusMarker route={route} lat={lat} lng={lng} />
      {snapped.map((s, i) => (
        <StopMarker key={s.id ?? i} lat={s.lat} lng={s.lng} name={s.name} index={i} />
      ))}
    </>
  );
}
