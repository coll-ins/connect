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
