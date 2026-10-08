"""Small geometry helpers for placing pickup stages along a route line."""
import math

MAX_STAGE_OFFSET_M = 300


def _project(lat, lng, lat0, lng0):
    return ((lng - lng0) * 111320 * math.cos(math.radians(lat0)), (lat - lat0) * 110540)


def locate_on_line(geometry, lat, lng):
    """Return (distance_m, along_m) for the nearest point on a GeoJSON LineString,
    or None when there is no usable line."""
    if not isinstance(geometry, dict) or geometry.get('type') != 'LineString':
        return None
    pts = []
    for c in geometry.get('coordinates') or []:
        try:
            pts.append((float(c[1]), float(c[0])))
        except (TypeError, ValueError, IndexError):
            return None
    if len(pts) < 2:
        return None
    lat0, lng0 = pts[0]
    xy = [_project(a, b, lat0, lng0) for a, b in pts]
    px, py = _project(lat, lng, lat0, lng0)
    best, walked = None, 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:]):
        dx, dy = x2 - x1, y2 - y1
        seg = math.hypot(dx, dy)
        if seg == 0:
            continue
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (seg * seg)))
        d = math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
        if best is None or d < best[0]:
            best = (d, walked + t * seg)
        walked += seg
    return best


SPUR_MIN_STEP_M = 25
SPUR_COS = math.cos(math.radians(150))


def line_health(geometry, stages):
    """Objective shape checks on a saved route line. These are hints for a
    person to look at, not proof that the line matches the road the bus uses.

    stages: iterable of (id, name, lat, lng).
    """
    result = {
        'has_line': False, 'length_km': None, 'detour_ratio': None,
        'spurs': 0, 'spur_points': [], 'stages_off': [],
    }
    if not isinstance(geometry, dict) or geometry.get('type') != 'LineString':
        return result
    pts = []
    for c in geometry.get('coordinates') or []:
        try:
            pts.append((float(c[1]), float(c[0])))
        except (TypeError, ValueError, IndexError):
            return result
    if len(pts) < 2:
        return result

    lat0, lng0 = pts[0]
    xy = [_project(a, b, lat0, lng0) for a, b in pts]
    length = sum(math.hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(xy, xy[1:]))
    straight = math.hypot(xy[-1][0] - xy[0][0], xy[-1][1] - xy[0][1])
    result['has_line'] = True
    result['length_km'] = round(length / 1000, 1)
    if straight > 0:
        result['detour_ratio'] = round(length / straight, 2)

    kept = [0]
    for k in range(1, len(xy)):
        last = xy[kept[-1]]
        if math.hypot(xy[k][0] - last[0], xy[k][1] - last[1]) >= SPUR_MIN_STEP_M:
            kept.append(k)
    for a, b, c in zip(kept, kept[1:], kept[2:]):
        v1 = (xy[b][0] - xy[a][0], xy[b][1] - xy[a][1])
        v2 = (xy[c][0] - xy[b][0], xy[c][1] - xy[b][1])
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 == 0 or n2 == 0:
            continue
        if (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2) < SPUR_COS:
            result['spurs'] += 1
            if len(result['spur_points']) < 5:
                result['spur_points'].append([pts[b][0], pts[b][1]])

    for sid, name, lat, lng in stages:
        loc = locate_on_line(geometry, lat, lng)
        if loc is not None and loc[0] > MAX_STAGE_OFFSET_M:
            result['stages_off'].append({'id': sid, 'name': name, 'offset_m': round(loc[0])})
    return result
