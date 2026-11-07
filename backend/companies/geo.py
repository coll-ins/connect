"""Small geometry helpers for placing pickup stages along a route line."""
import json
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


def haversine_m(a, b):
    dlat = math.radians(b[0] - a[0])
    dlng = math.radians(b[1] - a[1])
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0]))
        * math.sin(dlng / 2) ** 2
    )
    return 6371000.0 * 2 * math.asin(math.sqrt(h))


def parse_geometry(raw):
    """GeoJSON LineString/Feature/MultiLineString -> [(lat, lng), ...] or None."""
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict):
        return None
    if raw.get('type') == 'Feature':
        raw = raw.get('geometry') or {}
    if raw.get('type') == 'FeatureCollection':
        feats = raw.get('features') or []
        raw = (feats[0].get('geometry') if feats else {}) or {}
    kind, coords = raw.get('type'), raw.get('coordinates')
    if kind == 'LineString':
        pts = coords
    elif kind == 'MultiLineString':
        pts = [p for line in (coords or []) for p in line]
    else:
        return None
    out = []
    for p in pts or []:
        try:
            out.append((float(p[1]), float(p[0])))  # GeoJSON is [lng, lat]
        except (TypeError, ValueError, IndexError):
            continue
    return out if len(out) >= 2 else None


def orient_path(path, start):
    """Make the path begin at the end nearest the boarding stage."""
    if haversine_m(path[-1], start) < haversine_m(path[0], start):
        return list(reversed(path))
    return list(path)


def point_along(path, dist_m):
    remaining = dist_m
    for a, b in zip(path, path[1:]):
        seg = haversine_m(a, b)
        if seg == 0:
            continue
        if remaining <= seg:
            f = remaining / seg
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f), False
        remaining -= seg
    return path[-1], True


def resample_evenly(path, step_m):
    """Points spaced step_m apart along the line, including both ends."""
    total = sum(haversine_m(a, b) for a, b in zip(path, path[1:]))
    if total <= 0:
        return []
    count = max(2, round(total / step_m) + 1)
    return [
        point_along(path, total * i / (count - 1))[0] for i in range(count)
    ]
