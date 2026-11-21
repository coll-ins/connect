"""SACCO x route matrix (brief item 13): every Company and every Route in the database.

Runs on the real seeded SACCOs and routes. The migrations seed no stages, no
route line and no schedules, so the only data a route has beyond name and fare is
whatever the seed gives it (upstream removed the install_route_stages tool). Where
the data is missing the row says DATA-GAP and a clearly labelled synthetic
fixture (route_fixtures.py) lets the code path run anyway: a DATA-GAP is a
finding about the data, never a pass.

Set SIM_REPORT_PATH to write the table (docs/sacco-route-matrix.md).
"""
import datetime as dt
import math
import os
import traceback

from django.urls import reverse
from django.utils import timezone

from bookings import services
from bookings.models import Booking, BookingHold
from companies import geo
from companies.models import Route, Trip, TripSchedule
from drivers.models import Driver
from companies.trip_generation import regenerate_for_schedule

from . import route_fixtures as rf
from .base import POSTGRES, SimCase

COLUMNS = ['Stages', 'Geometry', 'Schedule', 'Book', 'Pay', 'Track', 'Complete',
           'Seats and fare', 'Concurrency', 'Isolation']
VERDICTS = ('PASS', 'FAIL', 'DATA-GAP', 'SKIPPED')


def in_kenya(lat, lng):
    return rf.KENYA_LAT[0] <= lat <= rf.KENYA_LAT[1] and rf.KENYA_LNG[0] <= lng <= rf.KENYA_LNG[1]


def validate_geometry(geometry, stages):
    assert isinstance(geometry, dict) and geometry.get('type') == 'LineString', 'not a LineString'
    coords = geometry.get('coordinates') or []
    assert len(coords) >= 2, f'{len(coords)} point(s)'
    for lng, lat in coords:
        assert all(isinstance(v, (int, float)) and math.isfinite(v) for v in (lat, lng)), 'non-numeric point'
        assert in_kenya(lat, lng), f'point outside Kenya: {lat},{lng}'
    along = []
    for stage in stages:
        located = geo.locate_on_line(geometry, float(stage.latitude), float(stage.longitude))
        assert located is not None, 'line unusable'
        assert located[0] <= geo.MAX_STAGE_OFFSET_M, f'stage {stage.name} is {located[0]:.0f} m off the line'
        along.append(located[1])
    assert along == sorted(along), 'stages are not in order along the line'


class RouteMatrixTests(SimCase):
    maxDiff = None

    # ------------------------------------------------------------ one route
    def step(self, row, column, fn, needs=()):
        blocked = [n for n in needs if row.get(n, '').startswith(('FAIL', 'SKIPPED'))]
        if blocked:
            row[column] = f'SKIPPED({blocked[0]} did not pass)'
            return
        try:
            row[column] = fn() or 'PASS'
        except Exception as exc:
            first = (str(exc).splitlines() or [type(exc).__name__])[0][:110]
            row[column] = f'FAIL({type(exc).__name__}: {first})'
            row.setdefault('traces', []).append(f'{column}: {traceback.format_exc(limit=4)}')

    def run_route(self, index, route, seeded, signup_user):
        company = route.company
        row = {'company': company.name, 'route': route.name, 'fare': route.price}
        ctx = {}
        stage_count, had_line, had_schedule = seeded

        def stages():
            found = list(route.pickup_stages.order_by('order', 'id'))
            orders = [s.order for s in found]
            assert orders == sorted(set(orders)), f'orders not strictly increasing: {orders}'
            for s in found:
                assert in_kenya(float(s.latitude), float(s.longitude)), f'{s.name} outside Kenya'
            ctx['stage_source'] = 'real'
            if len(found) >= 2:
                return f'PASS({len(found)} in order)'
            if len(found) < 2:
                # One real stage cannot make a route: the fixture replaces it
                # (test database only) rather than mixing real and invented points.
                route.pickup_stages.all().delete()
                self.add_stages(route, index)
                ctx['stage_source'] = 'synthetic'
            what = f'seed {stage_count}, found {len(found)}'
            return f'DATA-GAP({what}; {ctx["stage_source"]} stages used)'

        def geometry():
            current = Route.objects.get(pk=route.pk)
            found = list(current.pickup_stages.filter(is_active=True).order_by('order', 'id'))
            if current.geometry:
                validate_geometry(current.geometry, found)
                return f'PASS({len(current.geometry["coordinates"])} points)'
            points = [(s.name, float(s.latitude), float(s.longitude)) for s in found]
            current.geometry = rf.line_geometry(points)
            current.save(update_fields=['geometry'])
            validate_geometry(current.geometry, found)
            ctx['line'] = current.geometry['coordinates']
            return 'DATA-GAP(no line seeded; straight line through stages used, passes the same checks)'

        def schedule():
            driver = self.driver(company)
            ctx['driver'] = driver
            local = timezone.localtime() + dt.timedelta(hours=1)
            sched = TripSchedule.objects.create(
                route=route, driver=driver, capacity=14, days_of_week='0,1,2,3,4,5,6',
                departure_time=dt.time(local.hour, 0), auto_renew=True)
            # The function the generate_scheduled_trips command calls per schedule
            # (the command itself walks every schedule, which is slow in a loop).
            regenerate_for_schedule(sched, days=7, revive=False)
            again = Trip.objects.filter(route=route).count()
            regenerate_for_schedule(sched, days=7, revive=False)
            trips = list(Trip.objects.filter(route=route).order_by('departure_at'))
            assert trips, 'schedule generated no trips'
            assert len(trips) == again, 're-running the generator created duplicates'
            assert all(t.departure_at > timezone.now() - dt.timedelta(minutes=1) for t in trips), 'past trip generated'
            assert all(t.capacity == 14 and t.driver_id == driver.pk for t in trips)
            ctx['trips'] = trips
            return f'DATA-GAP({"none seeded" if not had_schedule else "seeded"}; fixture generated {len(trips)} trips)'

        def book():
            trip = ctx['trips'][0]
            # The generated trip is days away; the live flow needs boarding and
            # GPS inside the 30 minute auto-depart window, so it is moved to +20 min.
            self.depart_in(trip, 20)
            trip.refresh_from_db()
            ctx['trip'] = trip
            passenger = signup_user or self.user()
            ctx['passenger'] = passenger
            stage = self.first_stage(route)
            data = self.book(passenger, trip, 2, stage)
            booking = Booking.objects.get(pk=data['booking_id'])
            ctx['booking'] = booking
            assert booking.status == 'pending'
            assert booking.pickup_stage_id == stage.pk
            wait = (booking.held_until - timezone.now()).total_seconds()
            assert 9 * 60 <= wait <= 10 * 60 + 5, f'hold is {wait:.0f} s'
            assert booking.total_amount == route.price * 2, f'{booking.total_amount} != {route.price * 2}'

        def pay():
            booking, passenger = ctx['booking'], ctx['passenger']
            reference, event, response = self.pay(passenger, booking, mpesa=True)
            assert response.status_code == 200, response.status_code
            booking.refresh_from_db()
            payment = self.payment(booking)
            assert booking.status == 'confirmed' and payment.status == 'confirmed'
            assert payment.method == 'digital' and payment.amount == route.price * 2
            charge_calls = self.fake.calls_to('charge')[-1]['json']
            assert charge_calls['amount'] == int(route.price * 2 * 100), charge_calls['amount']
            assert BookingHold.objects.get(booking=booking).status == 'held'

        def seats_and_fare():
            trip, booking = ctx['trip'], ctx['booking']
            manager = self.staff(company, 'company_manager')
            assert services.seats_taken(trip) == 2
            summary = self.api(manager).get(reverse('trip-seat-summary', args=[trip.pk])).json()
            assert (summary['capacity'], summary['confirmed_seats'], summary['open_seats']) == (14, 2, 12), summary
            extra = self.user()
            second = self.booking(extra, trip, 1)
            assert services.seats_taken(trip) == 3
            self.cancel(extra, second)
            assert services.seats_taken(trip) == 2, 'cancelling a pending booking did not free its seat'
            assert booking.total_amount / booking.seats == route.price

        def track():
            trip, booking, passenger = ctx['trip'], ctx['booking'], ctx['passenger']
            manager = self.staff(company, 'company_manager')
            driver_user = ctx['driver'].account
            r = self.api(manager).post(reverse('update_trip_status', args=[trip.pk]), {'status': 'boarding'}, format='json')
            assert r.status_code == 200, r.content
            live = self.api(passenger).get(reverse('bookings:booking-live-location', args=[booking.pk]))
            assert live.status_code == 200, live.content
            r = self.api(driver_user).post(
                reverse('bookings:verify-boarding', args=[booking.pk]),
                {'boarding_pin': booking.verification_pin}, format='json')
            assert r.status_code == 200, r.content
            line = ctx.get('line') or [[float(s.longitude), float(s.latitude)]
                                       for s in route.pickup_stages.order_by('order', 'id')]
            now = timezone.now()
            from bookings.departure import _metres
            first = route.pickup_stages.filter(is_active=True).order_by('order', 'id').first()
            home = (float(first.latitude), float(first.longitude))
            # Auto-depart needs two fixes beyond its distance threshold from stage 1; dense
            # route lines can have several points inside it.
            away = [p for p in line if _metres(*home, p[1], p[0]) > 200]
            fixes = [[home[1], home[0]]] + (away[:2] if len(away) >= 2 else (away * 2 or line[-2:]))
            for k, (lng, lat) in enumerate(fixes):
                stamp = (now - dt.timedelta(seconds=10 - 3 * k)).isoformat()
                # Stages are kilometres apart: age the last fix so the speed check has nothing to compare.
                Driver.objects.filter(pk=ctx['driver'].pk).update(
                    location_updated_at=now - dt.timedelta(minutes=10))
                r = self.api(driver_user).post(
                    reverse('drivers:driver-location', args=[ctx['driver'].pk]),
                    {'latitude': lat, 'longitude': lng, 'fix_at': stamp, 'accuracy_m': 12}, format='json')
                assert r.status_code == 200 and not r.json().get('ignored'), r.content
            trip.refresh_from_db()
            assert trip.status == 'departed', f'two fixes away from stage 1 left the trip {trip.status}'
            live = self.api(passenger).get(reverse('bookings:booking-live-location', args=[booking.pk])).json()
            assert live['is_trip_live'] and not live['is_stale'], live
            assert abs(live['driver']['latitude'] - fixes[-1][1]) < 1e-5
            assert abs(live['driver']['longitude'] - fixes[-1][0]) < 1e-5

        def complete():
            trip, booking = ctx['trip'], ctx['booking']
            self.depart_in(trip, -25)
            r = self.api(ctx['driver'].account).post(
                reverse('bookings:driver-end-trip', args=[ctx['driver'].pk]), {}, format='json')
            assert r.status_code == 200, r.content
            trip.refresh_from_db()
            booking.refresh_from_db()
            payment = self.payment(booking)
            assert trip.status == 'completed' and booking.status == 'completed', (trip.status, booking.status)
            assert hasattr(booking, 'boarding_event')
            assert payment.settlement_status == 'eligible', payment.settlement_status
            assert BookingHold.objects.get(booking=booking).status == 'released'

        def concurrency():
            if not POSTGRES:
                return 'SKIPPED(sqlite has no row locks)'
            trip = ctx['trips'][-1]
            filler = self.user()
            Booking.objects.create(
                user=filler, trip=trip, route=route, driver=trip.driver, seats=trip.capacity - 1,
                total_amount=route.price * (trip.capacity - 1), status='confirmed',
                pickup_location='fixture')
            racers = [self.user() for _ in range(4)]
            stage = self.first_stage(route)

            def attempt(user):
                return lambda: self.api(user).post(
                    reverse('bookings:create-booking'),
                    {'trip_id': trip.pk, 'seats': 1, 'pickup_stage_id': stage.pk}, format='json').status_code

            codes, errors = self.run_threads([attempt(u) for u in racers])
            assert not errors, errors
            assert codes.count(201) == 1, codes
            assert services.seats_taken(trip) == trip.capacity

        def isolation():
            trip, booking, passenger = ctx['trip'], ctx['booking'], ctx['passenger']
            other = next(c for c in self.companies() if c.pk != company.pk)
            stranger = self.user()
            urls = [('get', reverse('bookings:get-booking-detail', args=[booking.pk])),
                    ('get', reverse('bookings:booking-live-location', args=[booking.pk])),
                    ('post', reverse('bookings:cancel-booking', args=[booking.pk]))]
            for who in [self.staff(other, r) for r in ('company_manager', 'company_operator', 'company_auditor')] + [stranger]:
                client = self.api(who)
                for method, url in urls:
                    code = getattr(client, method)(url, {}, format='json').status_code if method == 'post' else client.get(url).status_code
                    assert code in (403, 404), f'{who.role} of another party: {method} {url} -> {code}'
                body = client.get(reverse('bookings:get-all-bookings')).content.decode()
                assert booking.booking_number not in body, f'{who.role} lists this booking'
                if who.role != 'passenger':
                    assert client.get(reverse('trip-seat-summary', args=[trip.pk])).status_code in (403, 404)
                    assert client.post(reverse('update_trip_status', args=[trip.pk]), {'status': 'cancelled'}, format='json').status_code in (403, 404)
                    assert client.get(reverse('drivers:driver-location', args=[ctx['driver'].pk])).status_code in (403, 404)
            # Own staff and the owner do see it.
            assert self.api(self.staff(company, 'company_auditor')).get(
                reverse('bookings:get-booking-detail', args=[booking.pk])).status_code == 200
            assert self.api(passenger).get(
                reverse('bookings:get-booking-detail', args=[booking.pk])).status_code == 200
            assert Booking.objects.get(pk=booking.pk).status == 'completed', 'another party changed the booking'

        self.step(row, 'Stages', stages)
        self.step(row, 'Geometry', geometry, ['Stages'])
        self.step(row, 'Schedule', schedule, ['Stages'])
        self.step(row, 'Book', book, ['Stages', 'Schedule'])
        self.step(row, 'Pay', pay, ['Book'])
        self.step(row, 'Seats and fare', seats_and_fare, ['Pay'])
        self.step(row, 'Track', track, ['Pay', 'Geometry'])
        self.step(row, 'Complete', complete, ['Track'])
        self.step(row, 'Concurrency', concurrency, ['Schedule'])
        self.step(row, 'Isolation', isolation, ['Complete'])
        return row

    # ------------------------------------------------------------ the matrix
    def test_every_company_and_route(self):
        routes = list(Route.objects.select_related('company').order_by('company_id', 'id'))
        companies = list(Route.objects.values_list('company_id', flat=True).distinct())
        self.assertGreaterEqual(len(routes), 35)
        self.assertGreaterEqual(len(companies), 3)
        for company in self.companies():
            self.assertTrue(company.routes.exists(), f'{company.name} has no routes')

        seeded = {
            r.pk: (r.pickup_stages.count(), bool(r.geometry), r.schedules.count()) for r in routes}

        # One real sign-up per SACCO (the sign-up throttle makes more pointless).
        signups, seen = {}, set()
        for route in routes:
            if route.company_id in seen:
                continue
            seen.add(route.company_id)
            phone = self.phone()
            response = self.api(None).post(reverse('users:signup'), {
                'username': f'signup{route.company_id}', 'phone_number': phone,
                'name': 'Sim Passenger', 'password': 'Sim-pass-2026-xyz',
                'accept_terms': True}, format='json')
            self.assertEqual(response.status_code, 201, response.content)
            signups[route.pk] = self.user_by_phone(phone)

        rows = []
        for index, route in enumerate(routes):
            rows.append(self.run_route(index, route, seeded[route.pk], signups.get(route.pk)))

        report = render_report(rows, POSTGRES)
        path = os.environ.get('SIM_REPORT_PATH')
        if path:
            with open(path, 'w', encoding='utf-8', newline='\n') as handle:
                handle.write(report)

        problems = []
        for row in rows:
            for column in COLUMNS:
                cell = row.get(column, '')
                if not cell.startswith(VERDICTS):
                    problems.append(f'{row["company"]} / {row["route"]}: {column} is {cell!r}')
                if cell.startswith('FAIL'):
                    problems.append(f'{row["company"]} / {row["route"]}: {column} {cell}\n'
                                    + '\n'.join(row.get('traces', [])))
        self.assertEqual(problems, [])

    def user_by_phone(self, phone):
        from django.contrib.auth import get_user_model
        return get_user_model().objects.get(phone_number=phone)


# ------------------------------------------------------------------ report

def result_of(row):
    cells = [row[c] for c in COLUMNS]
    if any(c.startswith('FAIL') for c in cells):
        return 'FAIL'
    if any(c.startswith('SKIPPED') for c in cells):
        return 'UNPROVEN'
    if any(c.startswith('DATA-GAP') for c in cells):
        return 'DATA-GAP'
    return 'PASS'


def short(cell):
    """Table cell: the verdict word only; the reasons are listed once under the table."""
    return cell.split('(', 1)[0] if cell.startswith(('DATA-GAP', 'SKIPPED')) else cell


def render_report(rows, postgres):
    for row in rows:
        row['Result'] = result_of(row)
    counts = {k: sum(1 for r in rows if r['Result'] == k) for k in ('PASS', 'FAIL', 'DATA-GAP', 'UNPROVEN')}
    lines = [
        '# SACCO x route matrix',
        '',
        f'Generated by `bookings/tests/sim/test_route_matrix.py` on {"PostgreSQL" if postgres else "SQLite"} '
        f'against the migration-seeded SACCOs and routes (never edit by hand: rerun the test with SIM_REPORT_PATH set).',
        '',
        f'Rows: {len(rows)}. **PASS {counts["PASS"]} / FAIL {counts["FAIL"]} / '
        f'DATA-GAP {counts["DATA-GAP"]} / UNPROVEN {counts["UNPROVEN"]}**',
        '',
        'Result rule: any FAIL gives FAIL; else any SKIPPED gives UNPROVEN; else any DATA-GAP gives DATA-GAP; else PASS.',
        'A cell that says DATA-GAP means the seeded data lacks something; a synthetic fixture (route_fixtures.py, '
        'test database only) let the code path run, so Book/Pay/Track/Complete PASS prove the code, not the data.',
        '',
        '| SACCO | Route | Fare | ' + ' | '.join(COLUMNS) + ' | Result |',
        '|' + '---|' * (len(COLUMNS) + 4),
    ]
    for r in rows:
        lines.append(f'| {r["company"]} | {r["route"]} | {r["fare"]} | '
                     + ' | '.join(short(r[c]) for c in COLUMNS) + f' | **{r["Result"]}** |')
    lines += ['', '## Why each DATA-GAP / SKIPPED cell', '']
    for r in rows:
        why = [f'{c}: {r[c]}' for c in COLUMNS if r[c].startswith(('DATA-GAP', 'SKIPPED', 'FAIL'))]
        if why:
            lines.append(f'- **{r["company"]} / {r["route"]}**: ' + '; '.join(why))
    gap_routes = [f'{r["company"]} / {r["route"]}' for r in rows if r['Result'] == 'DATA-GAP']
    lines += ['', '## DATA-GAP routes', '', ', '.join(gap_routes) or 'none', '',
              '## Not proven by this table', '',
              '- The production SACCO and route list. This ran on the SACCOs and routes the migrations create, '
              'not on a production dump (brief decision 6). It stays UNPROVEN until Collins supplies the real list.',
              '- Stage and route-line coordinates: only stages the seed already holds are real; '
              'every other stage and every line is synthetic.',
              '- Paystack behaviour: the gateway is a fake that encodes this code\'s own assumptions (docs/plan.md V9).',
              '']
    return '\n'.join(lines)
