"""
Rebuild saved road lines from each route's start, end and road points.

Older lines were forced through every stage, so they swerve into side streets.
A rebuilt line follows the plain road between the start, the manager's road
points and the end, and is pulled through a stage only when the road misses it
by a clear margin and doing so does not make the line double back.

Dry run by default. --apply saves a route only when every stage ends up within
the allowed distance of the new line and no bus is running on it. Everything
else is listed for the Route planner. The line is still a routing service's
choice of road: review it in the planner and add road points where it differs
from the road the matatus use.
"""
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from companies.geo import line_health
from companies.models import Route, Trip


def _metres(a, b):
    import math

    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return round(12742000 * math.asin(math.sqrt(h)))


class Command(BaseCommand):
    help = 'Rebuild route lines without stage detours (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--route', type=int, action='append', dest='routes')
        parser.add_argument('--pause', type=float, default=1.0,
                            help='Seconds between routes, to be gentle with the road service.')
        parser.add_argument('--retries', type=int, default=3,
                            help='Tries per road-service call when it is busy.')
        parser.add_argument('--allow-spurs', action='store_true',
                            help='Also apply lines that still have spurs.')
        parser.add_argument('--no-follow-stages', action='store_true',
                            help='Ignore stages completely when building the line.')

    def handle(self, *args, **options):
        from companies.routing import RoutingError, plan_line, road_line

        queryset = Route.objects.order_by('id')
        if options['routes']:
            queryset = queryset.filter(pk__in=options['routes'])

        now = timezone.now()
        applied = review = skipped = 0

        for route in queryset:
            label = f'{route.id} {route.name}'
            coords = (route.start_latitude, route.start_longitude,
                      route.end_latitude, route.end_longitude)
            if any(c is None for c in coords):
                self.stdout.write(f'{label}: no start/end coordinates; set them in the Route planner')
                skipped += 1
                continue
            try:
                vias = [(float(v['latitude']), float(v['longitude']))
                        for v in (route.via_points or [])]
            except (KeyError, TypeError, ValueError):
                self.stdout.write(f'{label}: saved road points are unreadable; fix in the Route planner')
                skipped += 1
                continue

            start = (float(route.start_latitude), float(route.start_longitude))
            end = (float(route.end_latitude), float(route.end_longitude))
            stages = [(s.id, s.name, float(s.latitude), float(s.longitude))
                      for s in route.pickup_stages.filter(is_active=True)]
            old = line_health(route.geometry, stages)
            report = []

            try:
                if options['no_follow_stages']:
                    geometry, _distance = road_line([start, *vias, end])
                    followed = []
                else:
                    geometry, _distance, followed, _skipped = plan_line(
                        start, end, vias, stages, report=report, retries=options['retries'])
            except RoutingError as exc:
                self.stdout.write(f'{label}: road service said: {exc}')
                skipped += 1
                time.sleep(options['pause'])
                continue

            new = line_health(geometry, stages)
            running = Trip.objects.filter(
                route=route, status__in=['boarding', 'departed'],
                departure_at__gte=now - timedelta(hours=12),
                departure_at__lte=now + timedelta(hours=3),
            ).exists()

            summary = (f'{label}: {old["length_km"]} km, {old["spurs"]} spur(s) -> '
                       f'{new["length_km"]} km, {new["spurs"]} spur(s), '
                       f'pulled through {len(followed)} stage(s)')
            if new['stages_off']:
                names = ', '.join(s['name'] for s in new['stages_off'])
                self.stdout.write(f'{summary}; NEEDS YOU: stage(s) still off the line: {names}')
                by_id = {s[0]: s for s in stages}
                by_name = {s[1]: s for s in stages}
                tried = {n['stage_id'] for n in report}
                for note in report:
                    st = by_id[note['stage_id']]
                    self.stdout.write(
                        f"    - {st[1]}: {note['offset_m']} m off the plain road; {note['outcome']}; "
                        f"route end is {_metres(end, st[2:])} m from it")
                for s in new['stages_off']:
                    st = by_name.get(s['name'])
                    if st and st[0] not in tried:
                        self.stdout.write(
                            f"    - {st[1]}: not tried (inside the pull distance or past the 6-stage limit); "
                            f"route end is {_metres(end, st[2:])} m from it")
                review += 1
            elif running:
                self.stdout.write(f'{summary}; NEEDS YOU: a bus is running on this route now')
                review += 1
            elif new['spurs'] > 0 and not options['allow_spurs']:
                self.stdout.write(
                    f'{summary}; NEEDS YOU: the line still has {new["spurs"]} spur(s); '
                    'look at it in the Route planner')
                review += 1
            elif options['apply']:
                route.geometry = geometry
                route.save(update_fields=['geometry'])
                self.stdout.write(f'{summary}; applied')
                applied += 1
            else:
                self.stdout.write(f'{summary}; would apply')
            time.sleep(options['pause'])

        self.stdout.write(
            f'rebuild_route_lines: applied {applied}, need you {review}, skipped {skipped}'
            + ('' if options['apply'] else ' (dry run)'))
