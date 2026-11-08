"""Road traffic along a route, measured from our own buses' recent GPS.

Two consecutive real fixes from one bus give its speed over that stretch of
road. Speeds are binned along the route and labelled heavy, slow or moving.
No outside service: it only knows roads that CONNECT buses drove recently.
"""
import hashlib
import json
import logging
import math
import random
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from .models import LocationPing

logger = logging.getLogger(__name__)

KEEP = timedelta(hours=2)
WINDOW = timedelta(minutes=20)
FRESH_S = 5 * 60  # within a bin, only trust readings close to its newest one
SNAP_M = 35
STAGE_M = 60  # buses stop at stages on purpose; that is not traffic
TERMINUS_M = 150  # nor at either end of the route
PARKED_S = 5 * 60  # a bus not moving for this long is parked, not in traffic
STILL_M = 5
BIN_M = 150
CELL_M = 100
MAX_ROUTE_M = 500_000
HEAVY_KMH = 8
SLOW_KMH = 20
MIN_DT_S, MAX_DT_S = 3, 180
MAX_PINGS = 20000
CACHE_S = 30
EARTH_M = 6371000.0


def keep_ping(driver, latitude, longitude, at):
    # Traffic is optional: a failed write must never fail the driver's GPS post.
    try:
        LocationPing.objects.create(
            driver=driver, latitude=latitude, longitude=longitude, recorded_at=at,
        )
        # Cheap amortised clean-up instead of a cron job.
        if random.random() < 0.02:
            LocationPing.objects.filter(recorded_at__lt=at - KEEP).delete()
    except Exception:
        logger.exception('could not keep GPS ping for driver %s', driver.pk)


def _level(speed_kmh):
    if speed_kmh < HEAVY_KMH:
        return 'heavy'
    if speed_kmh < SLOW_KMH:
        return 'slow'
    return 'moving'


class _Line:
    """Route polyline in local metres, with a grid for fast snapping."""

    def __init__(self, coords):
        self.lat0 = math.radians(sum(c[1] for c in coords) / len(coords))
        # Split long segments so each one only touches a few grid cells.
        self.coords = [coords[0]]
        for a, b in zip(coords, coords[1:]):
            pieces = max(1, math.ceil(math.dist(self.project(a[1], a[0]), self.project(b[1], b[0])) / CELL_M))
            for k in range(1, pieces + 1):
                t = k / pieces
                self.coords.append([a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])])
        self.pts = [self.project(c[1], c[0]) for c in self.coords]
        self.cum = [0.0]
        for a, b in zip(self.pts, self.pts[1:]):
            self.cum.append(self.cum[-1] + math.dist(a, b))
        self.grid = {}
        for i, (a, b) in enumerate(zip(self.pts, self.pts[1:])):
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            for cx in range(int((x0 - SNAP_M) // CELL_M), int((x1 + SNAP_M) // CELL_M) + 1):
                for cy in range(int((y0 - SNAP_M) // CELL_M), int((y1 + SNAP_M) // CELL_M) + 1):
                    self.grid.setdefault((cx, cy), []).append(i)

    def project(self, lat, lng):
        return (
            EARTH_M * math.radians(lng) * math.cos(self.lat0),
            EARTH_M * math.radians(lat),
        )

    def snap(self, p):
        """Distance along the route of the nearest point, or None if off it."""
        best = None
        for i in self.grid.get((int(p[0] // CELL_M), int(p[1] // CELL_M)), ()):
            a, b = self.pts[i], self.pts[i + 1]
            dx, dy = b[0] - a[0], b[1] - a[1]
            seg2 = dx * dx + dy * dy
            t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / seg2))
            d = math.dist(p, (a[0] + t * dx, a[1] + t * dy))
            if d <= SNAP_M and (best is None or d < best[0]):
                best = (d, self.cum[i] + t * (self.cum[i + 1] - self.cum[i]))
        return None if best is None else best[1]

    def slice(self, start_m, end_m):
        out = []
        for i in range(len(self.coords) - 1):
            s0, s1 = self.cum[i], self.cum[i + 1]
            if s1 < start_m or s0 > end_m or s1 == s0:
                continue
            for m in (max(start_m, s0), min(end_m, s1)):
                t = (m - s0) / (s1 - s0)
                a, b = self.coords[i], self.coords[i + 1]
                point = [round(a[0] + t * (b[0] - a[0]), 6), round(a[1] + t * (b[1] - a[1]), 6)]
                if not out or out[-1] != point:
                    out.append(point)
        return out


def _route_coords(geometry):
    coords = geometry.get('coordinates') if isinstance(geometry, dict) else None
    if not isinstance(coords, list):
        return None
    try:
        clean = [[float(c[0]), float(c[1])] for c in coords]
    except (TypeError, ValueError, IndexError):
        return None
    if any(
        not (math.isfinite(lng) and math.isfinite(lat) and -180 <= lng <= 180 and -90 <= lat <= 90)
        for lng, lat in clean
    ):
        return None
    return clean if len(clean) >= 2 else None


def _route_length_m(coords):
    lat0 = math.radians(sum(c[1] for c in coords) / len(coords))
    scale = EARTH_M * math.pi / 180
    return sum(
        math.hypot((b[0] - a[0]) * math.cos(lat0), b[1] - a[1]) * scale
        for a, b in zip(coords, coords[1:])
    )


def _drop_parked(pairs):
    """Remove runs of a stationary bus that last longer than PARKED_S."""
    keep, run = [], []
    for pair in pairs + [None]:
        if pair is not None and pair['still']:
            run.append(pair)
            continue
        if run and (run[-1]['t'] - run[0]['t0']) < PARKED_S:
            keep.extend(run)
        run = []
        if pair is not None:
            keep.append(pair)
    return keep


def compute_traffic(coords, stages, pings, own_driver_id=None):
    """
    coords: route [[lng, lat], ...]; stages: [(lat, lng)];
    pings: [(driver_id, lat, lng, recorded_at)] sorted by driver then time.

    A stretch is only shown when two or more buses agree, or when all of its
    readings come from own_driver_id (the passenger's own bus, whose position
    they already see). One other company's bus is never traceable.
    """
    line = _Line(coords)
    total = line.cum[-1]
    stage_m = [m for m in (line.snap(line.project(lat, lng)) for lat, lng in stages) if m is not None]

    pairs_by_driver = {}
    prev = None
    for driver_id, lat, lng, at in pings:
        p = line.project(lat, lng)
        s = line.snap(p)
        if s is None:
            prev = None
            continue
        if prev and prev[0] == driver_id:
            _, p1, s1, t1 = prev
            dt = (at - t1).total_seconds()
            ds = s - s1
            mid = (s1 + s) / 2
            if (
                MIN_DT_S <= dt <= MAX_DT_S
                and ds > -20  # opposite direction on a two-way road
                and math.dist(p1, p) <= abs(ds) + 60  # took another road between fixes
                and TERMINUS_M <= mid <= total - TERMINUS_M
                and not any(abs(mid - m) < STAGE_M for m in stage_m)
            ):
                pairs_by_driver.setdefault(driver_id, []).append({
                    's1': s1, 's2': s, 't0': t1.timestamp(), 't': at.timestamp(),
                    'speed': max(ds, 0.0) / dt * 3.6,
                    'still': math.dist(p1, p) < STILL_M,
                })
        prev = (driver_id, p, s, at)

    bins = {}
    for driver_id, pairs in pairs_by_driver.items():
        for pair in _drop_parked(pairs):
            low, high = sorted((pair['s1'], pair['s2']))
            for b in range(int(low // BIN_M), int(high // BIN_M) + 1):
                bins.setdefault(b, []).append((pair['t'], pair['speed'], driver_id))

    levels = {}
    for b, readings in bins.items():
        newest = max(t for t, _, _ in readings)
        fresh = [(v, d) for t, v, d in readings if newest - t <= FRESH_S]
        drivers = {d for _, d in fresh}
        if len(drivers) < 2 and drivers != {own_driver_id}:
            continue
        speeds = sorted(v for v, _ in fresh)
        levels[b] = _level(speeds[len(speeds) // 2])

    segments = []
    for b in sorted(levels):
        if segments and segments[-1][0] == levels[b] and segments[-1][2] == b:
            segments[-1][2] = b + 1
        else:
            segments.append([levels[b], b, b + 1])

    out = []
    for level, start, end in segments:
        path = line.slice(start * BIN_M, min(end * BIN_M, total))
        if len(path) >= 2:
            out.append({'level': level, 'coordinates': path})
    return out


def route_traffic(route, own_driver_id=None):
    """Cached traffic segments for a route, or [] when nothing is known."""
    coords = _route_coords(getattr(route, 'geometry', None))
    if not coords or _route_length_m(coords) > MAX_ROUTE_M:
        return []
    digest = hashlib.sha1(json.dumps(coords).encode()).hexdigest()[:16]
    key = f'route-traffic:{route.id}:{digest}:{own_driver_id or 0}'
    cached = cache.get(key)
    if cached is not None:
        return cached

    lngs = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    margin = 0.001  # ~110 m
    newest = list(
        LocationPing.objects.filter(
            recorded_at__gte=timezone.now() - WINDOW,
            latitude__range=(min(lats) - margin, max(lats) + margin),
            longitude__range=(min(lngs) - margin, max(lngs) + margin),
        )
        .order_by('-recorded_at')
        .values_list('driver_id', 'latitude', 'longitude', 'recorded_at')[:MAX_PINGS]
    )
    pings = sorted(newest, key=lambda row: (row[0], row[3]))
    stages = [
        (float(s.latitude), float(s.longitude))
        for s in route.pickup_stages.filter(is_active=True)
        if s.latitude is not None and s.longitude is not None
    ]
    result = compute_traffic(coords, stages, pings, own_driver_id) if pings else []
    cache.set(key, result, CACHE_S)
    return result
