"""SHOWCASE: drive a bus along a real route through the real GPS endpoint.

Only the movement is simulated. Bookings, payments, boarding, the departure
trigger and the SMS are the production code paths. By default it talks to the
RUNNING server over HTTP, so websocket pushes happen inside that server.
"""
import random
import select
import sys
import time
from importlib import import_module

import requests
from django.conf import settings
from django.contrib.auth import (
    BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model,
)
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse
from rest_framework.test import APIClient

from companies.geo import haversine_m, orient_path, parse_geometry, point_along
from companies.models import Trip
from users.phone import phone_variants


def path_length_m(path):
    return sum(haversine_m(a, b) for a, b in zip(path, path[1:]))


def mask(phone):
    phone = phone or ''
    return phone[:7] + '***' + phone[-2:] if len(phone) > 9 else '***'


class Command(BaseCommand):
    help = 'SHOWCASE: move a bus along its route via the real GPS endpoint.'

    def add_arguments(self, parser):
        parser.add_argument('--trip', type=int, required=True, help='Trip id to drive.')
        parser.add_argument('--speed-kmh', type=float, default=40.0)
        parser.add_argument('--approach-m', type=float, default=0.0,
                            help='Start this many metres before the first stage and drive in.')
        parser.add_argument('--interval', type=float, default=3.0, help='Seconds between GPS fixes.')
        parser.add_argument('--no-wait', action='store_true', help='Do not wait for Enter before moving.')
        parser.add_argument('--base-url', default='http://127.0.0.1:8000',
                            help='Running backend (default http://127.0.0.1:8000).')
        parser.add_argument('--in-process', action='store_true',
                            help='Skip the server and call the view directly (no live-map push).')

    def handle(self, *args, **opts):
        if not settings.DEBUG or settings.APP_ENVIRONMENT == 'production':
            raise CommandError(
                'simulate_bus is limited to non-production DEBUG environments.'
            )
        from bookings.models import Booking

        trips = Trip.objects.select_related('route', 'driver')
        trip = trips.filter(pk=opts['trip']).first()
        if trip is None:
            raise CommandError(f'Trip {opts["trip"]} not found.')
        driver, route = trip.driver, trip.route
        stage = route.pickup_stages.filter(is_active=True).order_by('order', 'id').first()
        if stage is None:
            raise CommandError(f'Route "{route.name}" has no active first stage.')
        start = (float(stage.latitude), float(stage.longitude))

        User = get_user_model()
        user = User.objects.filter(
            role='driver', company_id=driver.company_id,
            phone_number__in=phone_variants(driver.phone_number),
        ).first()
        if user is None:
            raise CommandError('No driver login matches this driver. Run seed_demo first.')

        geometry = parse_geometry(route.geometry)
        if geometry:
            path = [start] + orient_path(geometry, start)
            source = f'route geometry ({len(geometry)} points)'
        else:
            pts = [(float(s.latitude), float(s.longitude))
                   for s in route.pickup_stages.filter(is_active=True).order_by('order', 'id')]
            if route.end_latitude is not None and route.end_longitude is not None:
                pts.append((float(route.end_latitude), float(route.end_longitude)))
            path, source = pts, 'stage-to-stage straight lines (route has no geometry)'
        if len(path) < 2:
            raise CommandError('Not enough path points to move along.')
        total = path_length_m(path)

        url_path = reverse('drivers:driver-location', kwargs={'driver_id': driver.id})
        interval, speed = opts['interval'], opts['speed_kmh']
        store = None

        if opts['in_process']:
            client = APIClient()
            client.force_authenticate(user=user)

            def send(lat, lng):
                resp = client.post(url_path, {'latitude': lat, 'longitude': lng}, format='json')
                return resp.status_code, resp.get('Retry-After')
            mode = 'in-process (live-map pushes will NOT reach the running server)'
        else:
            base = opts['base_url'].rstrip('/')
            store = import_module(settings.SESSION_ENGINE).SessionStore()
            store[SESSION_KEY] = user._meta.pk.value_to_string(user)
            store[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
            store[HASH_SESSION_KEY] = user.get_session_auth_hash()
            store.save()
            http = requests.Session()
            http.cookies.set(settings.SESSION_COOKIE_NAME, store.session_key)
            try:
                http.get(f'{base}/api/users/csrf/', timeout=10)
            except requests.RequestException as exc:
                store.delete()
                raise CommandError(
                    f'Backend not reachable at {base} ({exc.__class__.__name__}). '
                    'Start it, or pass --base-url / --in-process.')
            token = http.cookies.get('csrftoken')
            if not token:
                store.delete()
                raise CommandError('The server did not issue a CSRF token at /api/users/csrf/.')
            headers = {'X-CSRFToken': token, 'Origin': 'http://localhost:5173',
                       'Referer': 'http://localhost:5173/'}

            def send(lat, lng):
                resp = http.post(f'{base}{url_path}', json={'latitude': lat, 'longitude': lng},
                                 headers=headers, timeout=15)
                return resp.status_code, resp.headers.get('Retry-After')
            mode = f'HTTP to {base} (pushes happen inside the running server)'

        def post(lat, lng):
            while True:
                code, retry = send(round(lat, 6), round(lng, 6))
                if code != 429:
                    return code
                try:
                    wait = int(retry)
                except (TypeError, ValueError):
                    wait = 5
                self.stdout.write(f'  throttled, waiting {wait}s')
                time.sleep(wait)

        self.stdout.write(
            f'Trip {trip.id} | {route.name} | bus {driver.bus_number}\n'
            f'Path: {source}, {total / 1000:.1f} km | boarding stage: {stage.name}\n'
            f'Speed {speed:.0f} km/h, one fix every {interval:.0f}s | mode: {mode}')

        try:
            if opts['approach_m'] > 0:
                nxt = next((q for q in path[1:] if haversine_m(start, q) > 100), path[-1])
                dn = haversine_m(start, nxt) or 1.0
                k = opts['approach_m'] / dn
                far = (start[0] + (start[0] - nxt[0]) * k,
                       start[1] + (start[1] - nxt[1]) * k)
                self.stdout.write(f'\nBus parked {opts["approach_m"]:.0f} m before {stage.name}. Press ENTER to send it in.')
                while True:
                    code = post(far[0] + random.uniform(-0.00003, 0.00003),
                                far[1] + random.uniform(-0.00003, 0.00003))
                    trip.refresh_from_db()
                    self.stdout.write(f'[approach-wait] HTTP {code} | trip={trip.status}')
                    if code in (401, 403):
                        raise CommandError(f'Server refused the driver login (HTTP {code}).')
                    if trip.status == 'departed':
                        raise CommandError('Trip departed: auto-depart window is open. Use a trip departing later.')
                    if select.select([sys.stdin], [], [], interval)[0]:
                        sys.stdin.readline()
                        break
                dist = haversine_m(far, start)
                travelled, step = 0.0, speed / 3.6 * interval
                while travelled < dist:
                    travelled = min(travelled + step, dist)
                    f = travelled / dist
                    code = post(far[0] + (start[0] - far[0]) * f,
                                far[1] + (start[1] - far[1]) * f)
                    trip.refresh_from_db()
                    self.stdout.write(f'[approach] {dist - travelled:6.0f} m to stage | HTTP {code} | trip={trip.status}')
                    if trip.status == 'departed':
                        raise CommandError('Trip departed during approach: auto-depart window is open.')
                    time.sleep(interval)
            if not opts['no_wait']:
                self.stdout.write('\nBus is at the stage. Press ENTER to start moving.')
                while True:
                    code = post(start[0] + random.uniform(-0.00003, 0.00003),
                                start[1] + random.uniform(-0.00003, 0.00003))
                    trip.refresh_from_db()
                    self.stdout.write(f'[wait] HTTP {code} | trip={trip.status} | boarding at {stage.name}')
                    if code in (401, 403):
                        raise CommandError(
                            f'Server refused the driver login (HTTP {code}). Paste this line to me.')
                    if select.select([sys.stdin], [], [], interval)[0]:
                        sys.stdin.readline()
                        break

            travelled, step, announced = 0.0, speed / 3.6 * interval, False
            while True:
                travelled += step
                (lat, lng), done = point_along(path, travelled)
                code = post(lat, lng)
                trip.refresh_from_db()
                self.stdout.write(
                    f'[{time.strftime("%H:%M:%S")}] {min(travelled, total) / 1000:5.2f}/{total / 1000:.2f} km'
                    f' | HTTP {code} | trip={trip.status}')
                if trip.status == 'departed' and not announced:
                    announced = True
                    confirmed = Booking.objects.filter(trip=trip, status='confirmed').select_related('user')
                    boarded = Booking.objects.filter(trip=trip, status='completed').count()
                    self.stdout.write(self.style.SUCCESS(
                        f'  AUTO-DEPARTED. Departure SMS goes to {confirmed.count()} confirmed '
                        f'passenger(s) who have not boarded; {boarded} already on the bus.'))
                    for b in confirmed:
                        self.stdout.write(f'    -> {mask(b.user.phone_number)} ({b.booking_number})')
                if done:
                    break
                time.sleep(interval)
            self.stdout.write(self.style.SUCCESS(
                'Arrived at the end of the route. The trip stays "departed": ending a trip '
                'is a real driver action with a minimum-duration rule.'))
        except KeyboardInterrupt:
            self.stdout.write('\nStopped.')
        finally:
            if store is not None:
                store.delete()
