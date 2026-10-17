"""
Rebuild saved road lines from each route's start, end and road points.

Older lines were forced through every stage, so they swerve into side streets.
A rebuilt line follows the road between the start, the manager's road points
and the end. Stages are only checked afterwards.

Dry run by default. --apply saves a route only when no stage would end up more
than the allowed distance from the new line and no bus is running on it.
Everything else is listed for the Route planner. The line is OSRM's road
choice, which may differ from the road the matatus use: review it in the
planner and add road points where it differs.
"""
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from companies.geo import line_health
from companies.models import Route, Trip


class Command(BaseCommand):
    help = 'Rebuild route lines without stage detours (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--route', type=int, action='append', dest='routes')
        parser.add_argument('--pause', type=float, default=1.0,
                            help='Seconds between road-service calls.')

    def handle(self, *args, **options):
        from companies.routing import RoutingError, road_line

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

            points = [(float(route.start_latitude), float(route.start_longitude)),
                      *vias,
                      (float(route.end_latitude), float(route.end_longitude))]
            stages = [(s.id, s.name, float(s.latitude), float(s.longitude))
                      for s in route.pickup_stages.filter(is_active=True)]
            old = line_health(route.geometry, stages)

            try:
                geometry, _distance = road_line(points)
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
                       f'{new["length_km"]} km, {new["spurs"]} spur(s)')
            if new['stages_off']:
                names = ', '.join(s['name'] for s in new['stages_off'])
                self.stdout.write(f'{summary}; NEEDS YOU: stage(s) would be off the line: {names}')
                review += 1
            elif running:
                self.stdout.write(f'{summary}; NEEDS YOU: a bus is running on this route now')
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
