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
