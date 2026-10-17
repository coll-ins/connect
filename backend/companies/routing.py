"""Road-following line generation. The service address is configurable."""
import json
import urllib.request

from django.conf import settings


class RoutingError(Exception):
    pass


def road_line(points):
    """points = [(lat, lng), ...]. Returns (GeoJSON LineString, distance in metres)."""
    base = getattr(settings, 'ROUTING_URL', 'https://router.project-osrm.org/route/v1/driving')
    coords = ';'.join(f'{lng:.6f},{lat:.6f}' for lat, lng in points)
    url = f'{base}/{coords}?overview=full&geometries=geojson&steps=false&continue_straight=true'
    req = urllib.request.Request(url, headers={'User-Agent': 'ConnectMatatuBooking/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as exc:
        raise RoutingError('The road service is not reachable right now. Try again in a moment.') from exc
    if data.get('code') != 'Ok' or not data.get('routes'):
        raise RoutingError('No road was found between these points. Move a point closer to a road.')
    best = data['routes'][0]
    geometry = best.get('geometry') or {}
    if geometry.get('type') != 'LineString' or len(geometry.get('coordinates') or []) < 2:
        raise RoutingError('The road service returned an unusable line.')
    return geometry, float(best.get('distance') or 0)


STAGE_PULL_M = 150
MAX_PULLED_STAGES = 6


def _road_line_retry(points, retries):
    """road_line, trying again after a pause when the road service is busy."""
    import time

    tries = max(1, retries)
    for attempt in range(tries):
        try:
            return road_line(points)
        except RoutingError:
            if attempt + 1 >= tries:
                raise
            time.sleep(2 * (attempt + 1))


def plan_line(start, end, vias, stages, report=None, retries=1):
    """Road line from start to end through the manager's road points.

    Stages do not steer the line unless the plain road misses them by more
    than STAGE_PULL_M. Each missed stage is added as a waypoint only if that
    brings the stage onto the line without making the line double back.

    start, end: (lat, lng). vias: [(lat, lng)] in travel order.
    stages: [(id, name, lat, lng)].
    Returns (geometry, distance_m, followed_stage_ids, skipped_stage_ids).
    """
    from .geo import line_health, locate_on_line

    notes = report if report is not None else []
    geometry, distance = _road_line_retry([start, *vias, end], retries)
    spurs = line_health(geometry, [])['spurs']
    ordered = [(None, tuple(v)) for v in vias]
    followed, skipped = [], []

    for _ in range(MAX_PULLED_STAGES):
        worst = None
        for sid, _name, lat, lng in stages:
            if sid in followed or sid in skipped:
                continue
            loc = locate_on_line(geometry, lat, lng)
            if loc is not None and loc[0] > STAGE_PULL_M and (worst is None or loc[0] > worst[0]):
                worst = (loc[0], sid, (lat, lng))
        if worst is None:
            break
        _offset, sid, point = worst

        placed = []
        for item in ordered + [(sid, point)]:
            loc = locate_on_line(geometry, item[1][0], item[1][1])
            placed.append((loc[1] if loc else 0.0, item))
        placed.sort(key=lambda entry: entry[0])
        candidate = [item for _along, item in placed]

        try:
            new_geometry, new_distance = _road_line_retry(
                [start, *[p for _id, p in candidate], end], retries)
        except RoutingError as exc:
            skipped.append(sid)
            notes.append({'stage_id': sid, 'offset_m': round(_offset),
                          'outcome': f'road service failed ({exc})'})
            continue

        here = locate_on_line(new_geometry, point[0], point[1])
        new_spurs = line_health(new_geometry, [])['spurs']
        if here is None or here[0] > STAGE_PULL_M or new_spurs > spurs:
            skipped.append(sid)
            if here is None or here[0] > STAGE_PULL_M:
                outcome = ('road did not reach it: still '
                           f'{round(here[0]) if here else "?"} m off')
            else:
                outcome = f'pulling it in adds {new_spurs - spurs} spur(s)'
            notes.append({'stage_id': sid, 'offset_m': round(_offset), 'outcome': outcome})
            continue

        geometry, distance, ordered, spurs = new_geometry, new_distance, candidate, new_spurs
        followed.append(sid)

    return geometry, distance, followed, skipped
