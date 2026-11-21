"""SYNTHETIC stage coordinates and route lines for the simulation. Test DB only.

These points are NOT surveyed data. They sit inside the Nairobi area on a
straight line from a start near Kencom to an end that depends on the route's
position in the list, so every route gets distinct, valid, ordered stages.
A row of docs/sacco-route-matrix.md that needed them says DATA-GAP: they prove
the code path, they are not evidence that production has real stages.
"""
import math
from decimal import Decimal

KENYA_LAT = (-4.7, 5.1)
KENYA_LNG = (33.9, 41.9)
START = (-1.2856, 36.8250)


def end_point(index):
    """A point 4 to 24 km from START, spread around the compass by route index."""
    bearing = math.radians((index * 47) % 360)
    km = 4 + (index % 6) * 4
    lat = START[0] + (km / 111.0) * math.cos(bearing)
    lng = START[1] + (km / (111.0 * math.cos(math.radians(START[0])))) * math.sin(bearing)
    return lat, lng


def stage_points(index, count=3):
    """[(name, lat, lng), ...] with count stages from START to end_point(index)."""
    end = end_point(index)
    out = []
    for k in range(count):
        t = k / (count - 1)
        lat = START[0] + (end[0] - START[0]) * t
        lng = START[1] + (end[1] - START[1]) * t
        out.append((f'SIM stage {k + 1}', round(lat, 6), round(lng, 6)))
    return out


def line_geometry(points):
    """GeoJSON LineString through the stage points, with one extra vertex per leg."""
    coords = []
    for (_, a_lat, a_lng), (_, b_lat, b_lng) in zip(points, points[1:]):
        coords.append([a_lng, a_lat])
        coords.append([round((a_lng + b_lng) / 2, 6), round((a_lat + b_lat) / 2, 6)])
    last = points[-1]
    coords.append([last[2], last[1]])
    return {'type': 'LineString', 'coordinates': coords}


def install(route, index, count=3):
    """Create synthetic stages for `route` (the line is added separately). Returns the stage rows."""
    from companies.models import PickupStage

    points = stage_points(index, count)
    stages = [
        PickupStage.objects.create(
            route=route, name=name, order=order, is_active=True, source='manual',
            latitude=Decimal(str(lat)), longitude=Decimal(str(lng)))
        for order, (name, lat, lng) in enumerate(points, start=1)
    ]
    return stages
