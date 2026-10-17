"""
Rebuild each route line without stage detours, then snap stages onto it.
Saves a route only if: every stage is within 600 m of the new line, the line has
0 spurs, and no bus is running. Dry run unless --apply.
"""
import math
import time
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from companies.geo import line_health
from companies.models import Route, Trip

TOLERANCE_M = 600.0


def project(lat, lng, coords):
    """Nearest point on a [[lng, lat], ...] line: (distance_m, lat, lng)."""
    k = math.cos(math.radians(lat)) * 111320.0
    best = None
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        ax, ay = (x1 - lng) * k, (y1 - lat) * 110574.0
        bx, by = (x2 - lng) * k, (y2 - lat) * 110574.0
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        t = 0 if seg == 0 else max(0, min(1, -(ax * dx + ay * dy) / seg))
        px, py = ax + t * dx, ay + t * dy
        d = math.hypot(px, py)
        if best is None or d < best[0]:
            best = (d, lat + py / 110574.0, lng + px / k)
    return best


class Command(BaseCommand):
    help = 'Rebuild route lines and snap stages onto them (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--route', type=int, action='append', dest='routes')
        parser.add_argument('--pause', type=float, default=1.0)

    def handle(self, *args, **options):
        from companies.routing import RoutingError, road_line

        qs = Route.objects.order_by('id')
        if options['routes']:
            qs = qs.filter(pk__in=options['routes'])
        now = timezone.now()
        done = blocked = skipped = 0

        for route in qs:
            label = f'{route.id} {route.name}'
            if any(c is None for c in (route.start_latitude, route.start_longitude,
                                       route.end_latitude, route.end_longitude)):
                self.stdout.write(f'{label}: no start/end; set them in the Route planner')
                skipped += 1
                continue
            try:
                vias = [(float(v['latitude']), float(v['longitude']))
                        for v in (route.via_points or [])]
                points = [(float(route.start_latitude), float(route.start_longitude)),
                          *vias,
                          (float(route.end_latitude), float(route.end_longitude))]
                geometry, _ = road_line(points)
            except (RoutingError, KeyError, TypeError, ValueError) as exc:
                self.stdout.write(f'{label}: cannot build line: {exc}')
                skipped += 1
                time.sleep(options['pause'])
                continue

            coords = geometry['coordinates']
            stages = list(route.pickup_stages.filter(is_active=True))
            fits = [(s, *project(float(s.latitude), float(s.longitude), coords)) for s in stages]
            far = [(s, d) for s, d, _, _ in fits if d > TOLERANCE_M]
            spurs = line_health(
                geometry, [(s.id, s.name, float(s.latitude), float(s.longitude)) for s in stages]
            )['spurs']
            running = Trip.objects.filter(
                route=route, status__in=['boarding', 'departed'],
                departure_at__gte=now - timedelta(hours=12),
                departure_at__lte=now + timedelta(hours=3)).exists()

            if far:
                detail = ', '.join(f'{s.name} {d:.0f} m' for s, d in far)
                self.stdout.write(f'{label}: BLOCKED, stage(s) over {TOLERANCE_M:.0f} m from the road: {detail}')
                blocked += 1
            elif spurs:
                self.stdout.write(f'{label}: BLOCKED, new line still has {spurs} spur(s); '
                                  f'start or end point is probably off the road, move it in the planner')
                blocked += 1
            elif running:
                self.stdout.write(f'{label}: BLOCKED, a bus is running on this route')
                blocked += 1
            elif options['apply']:
                with transaction.atomic():
                    route.geometry = geometry
                    route.save(update_fields=['geometry'])
                    for s, d, lat, lng in fits:
                        if d > 1:
                            s.latitude = Decimal(f'{lat:.6f}')
                            s.longitude = Decimal(f'{lng:.6f}')
                            s.save(update_fields=['latitude', 'longitude'])
                self.stdout.write(f'{label}: applied, {len(stages)} stage(s) snapped, 0 spurs')
                done += 1
            else:
                self.stdout.write(f'{label}: would apply, {len(stages)} stage(s) snapped, 0 spurs')
                done += 1
            time.sleep(options['pause'])

        self.stdout.write(f'fix_route_lines: ok {done}, blocked {blocked}, skipped {skipped}'
                          + ('' if options['apply'] else ' (dry run)'))
