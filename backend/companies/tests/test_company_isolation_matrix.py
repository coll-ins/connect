"""
Per-company isolation matrix (plan 8.4).

1. Every URL pattern must be classified. A new, unnamed or unclassified route fails
   this test, so the list cannot rot.
2. Every company-scoped route that takes an id is called by company A staff with a
   company B id: it must answer 403/404 (or the same 400 a missing id gets), leak no
   B data and change nothing.
"""
import datetime as dt
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import get_resolver
from django.utils import timezone
from rest_framework.test import APIClient

from buses.models import Bus
from bookings.models import Booking, Incident
from charters.models import CharterRequest
from companies.models import Company, PickupStage, Route, Trip, TripSchedule
from deliveries.models import Parcel
from drivers.models import Driver

User = get_user_model()

PUBLIC = 'public'            # no login needed; returns only data meant for everyone
OWN = 'own-data'             # any logged-in user, scoped to the caller's own rows
COMPANY = 'company-scoped'   # company staff, scoped to the caller's company
ADMIN = 'admin-only'         # platform superuser
INBOUND = 'inbound-secret'   # called by a machine with a signature or secret

CLASSIFICATION = {
    'root': PUBLIC, 'health-check': PUBLIC, 'users:csrf-token': PUBLIC,
    'users:user-api-root': PUBLIC, 'users:signup': PUBLIC, 'users:register': PUBLIC,
    'users:login': PUBLIC, 'users:admin-signup': PUBLIC,
    'get_companies': PUBLIC, 'get_routes': PUBLIC, 'get_company_routes': PUBLIC,
    'get_trips': PUBLIC, 'get_company_trips': PUBLIC, 'get_trip_details': PUBLIC,
    'get-trips': PUBLIC, 'get-trip-details': PUBLIC, 'route-map-data': PUBLIC,
    'system-diagnostics': ADMIN, 'start-trip-simulation': ADMIN, 'finish-simulated-trip': ADMIN,
    'divert-trip-simulation': ADMIN, 'active-trip-simulation': ADMIN,
    'advance-trip-simulation': ADMIN, 'stop-trip-simulation': ADMIN,
    'create_company': ADMIN, 'update_company': ADMIN,
    'bookings:paystack-webhook': INBOUND, 'bookings:paystack-refund-webhook': INBOUND,
    'cron-job': INBOUND,
    'users:logout': OWN, 'users:profile': OWN, 'users:user_profile': OWN,
    'bookings:create-booking': OWN, 'bookings:get-my-bookings': OWN,
    'bookings:passenger-records': OWN, 'bookings:get-booking-detail': OWN,
    'bookings:cancel-booking': OWN, 'bookings:resolve-incident-booking': OWN,
    'bookings:booking-replacement-trips': OWN, 'bookings:update-passenger-location': OWN,
    'bookings:booking-live-location': OWN, 'bookings:booking-reroute': OWN,
    'bookings:initialize-paystack-payment': OWN, 'bookings:initialize-mpesa-payment': OWN,
    'bookings:payment-status': OWN, 'bookings:verify-paystack-payment': OWN,
    'bookings:initialize-cash-payment': OWN, 'bookings:pay-from-wallet': OWN,
    'drivers:my-driver-profile': OWN, 'drivers:my-driver-timetable': OWN,
    'my-wallet': OWN, 'wallet-topup': OWN, 'wallet-topup-status': OWN,
    'wallet-transactions': OWN,
    'wallet-withdraw': OWN, 'wallet-withdrawals': OWN,
    'deliveries:parcel-list-create': OWN, 'deliveries:parcel-quote': OWN,
    'deliveries:parcel-options': OWN, 'deliveries:parcel-detail': OWN,
    'deliveries:parcel-cancel': OWN, 'deliveries:parcel-pay': OWN,
    'charters:charter-list-create': OWN, 'charters:charter-companies': OWN,
    'charters:charter-detail': OWN, 'charters:charter-cancel': OWN,
    'charters:charter-pay': OWN,
    'route_health': COMPANY, 'create_route': COMPANY, 'manage_route': COMPANY,
    'get_route_pickup_stages': COMPANY, 'create_pickup_stage': COMPANY,
    'route_plan': COMPANY, 'route_alternatives': COMPANY, 'manage_pickup_stage': COMPANY,
    'approve_pickup_stage': COMPANY, 'deactivate_pickup_stage': COMPANY,
    'create_trip': COMPANY, 'list_schedules': COMPANY,
    'list_schedule_generation_exceptions': COMPANY, 'list_weekly_operations_reports': COMPANY,
    'create_schedule': COMPANY, 'manage_schedule': COMPANY, 'booking-settings': COMPANY,
    'trip-seat-summary': COMPANY, 'update_trip_status': COMPANY, 'update_trip_capacity': COMPANY,
    'operator_route_assignments': COMPANY, 'set_operator_routes': COMPANY,
    'company_analytics': COMPANY,
    'users:company-staff': COMPANY, 'users:company-staff-detail': COMPANY,
    'bookings:auditor-receipt-search': COMPANY, 'bookings:walk-in-booking': COMPANY,
    'bookings:staff-alerts': COMPANY, 'bookings:get-all-bookings': COMPANY,
    'bookings:assign-driver': COMPANY, 'bookings:move-booking-to-trip': COMPANY,
    'bookings:verify-boarding': COMPANY, 'bookings:set-stage-departure': COMPANY,
    'bookings:get-driver-bookings': COMPANY, 'bookings:driver-end-trip': COMPANY,
    'bookings:incident-list': COMPANY, 'bookings:report-incident': COMPANY,
    'bookings:incident-detail': COMPANY, 'bookings:confirm-cash-payment': COMPANY,
    'drivers:driver-list': COMPANY, 'drivers:driver-detail': COMPANY,
    'drivers:driver-location': COMPANY,
    'buses:bus-list': COMPANY, 'buses:bus-detail': COMPANY,
    'deliveries:driver-parcels': COMPANY, 'deliveries:company-parcels': COMPANY,
    'deliveries:route-rates': COMPANY, 'deliveries:route-rates-update': COMPANY,
    'deliveries:parcel-verify': COMPANY, 'deliveries:parcel-pickup': COMPANY,
    'deliveries:parcel-deliver': COMPANY,
    'charters:charter-company': COMPANY, 'charters:charter-driver': COMPANY,
    'charters:charter-settings': COMPANY, 'charters:charter-quote': COMPANY,
    'charters:charter-decline': COMPANY, 'charters:charter-verify': COMPANY,
    'charters:charter-complete': COMPANY,
}


def all_url_names():
    """(name, pattern) for every non-Django-admin route; name is None when the route has none."""
    found = []

    def walk(patterns, prefix='', namespace=''):
        for entry in patterns:
            if hasattr(entry, 'url_patterns'):
                walk(entry.url_patterns, prefix + str(entry.pattern),
                     namespace + (entry.namespace + ':' if entry.namespace else ''))
            else:
                found.append((namespace + entry.name if entry.name else None,
                              prefix + str(entry.pattern)))

    walk(get_resolver().url_patterns)
    return [(n, p) for n, p in found if not p.startswith('admin/')]


class UrlClassificationTests(TestCase):
    def test_isolation_matrix_covers_every_url_name(self):
        routes = all_url_names()
        unnamed = [p for n, p in routes if n is None]
        self.assertEqual(unnamed, [], 'every route needs a name so it can be classified')
        unclassified = sorted({n for n, _ in routes} - set(CLASSIFICATION))
        self.assertEqual(unclassified, [], 'classify these in CLASSIFICATION')

    def test_classification_has_no_stale_names(self):
        self.assertEqual(sorted(set(CLASSIFICATION) - {n for n, _ in all_url_names()}), [])


class MatrixBase(TestCase):
    """Company A (the attacker's) and company B (the victim's), one of everything."""

    def setUp(self):
        mk = User.objects.create_user
        self.a = Company.objects.create(name='A Sacco', areas_served='Nairobi')
        self.b = Company.objects.create(name='ZZB Sacco', areas_served='ZZB-Kisumu')
        self.route_a = Route.objects.create(
            company=self.a, name='A Route', start_point='A1', end_point='A2', price=Decimal('100'))
        self.route_b = Route.objects.create(
            company=self.b, name='ZZB Route', start_point='ZZB-1', end_point='ZZB-2',
            price=Decimal('250'))
        self.stage_b = PickupStage.objects.create(
            route=self.route_b, name='ZZB Stage', order=1,
            latitude=Decimal('-0.10'), longitude=Decimal('34.75'))
        self.stage_b2 = PickupStage.objects.create(
            route=self.route_b, name='ZZB Stage 2', order=2,
            latitude=Decimal('-0.20'), longitude=Decimal('34.85'))
        self.driver_a = Driver.objects.create(
            name='Driver A', phone_number='+254700000011', bus_number='KAA 001A', company=self.a)
        self.driver_b = Driver.objects.create(
            name='ZZB Driver', phone_number='+254700000022', bus_number='ZZB 002B', company=self.b)
        self.trip_b = Trip.objects.create(
            route=self.route_b, driver=self.driver_b, capacity=10, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=5))
        self.pax_b = mk(username='paxb', password='pw-123456', phone_number='+254711900001')
        self.booking_b = Booking.objects.create(
            user=self.pax_b, trip=self.trip_b, route=self.route_b, driver=self.driver_b, seats=1,
            total_amount=Decimal('250'), status='confirmed', pickup_location='ZZB Stage',
            pickup_stage=self.stage_b)
        self.incident_b = Incident.objects.create(
            trip=self.trip_b, incident_type='breakdown', description='ZZB engine fire')
        self.bus_b = Bus.objects.create(
            company=self.b, registration_number='ZZB-REG-1', bus_number='ZZB-9', capacity=14)
        self.parcel_b = Parcel.objects.create(
            sender=self.pax_b, trip=self.trip_b, pickup_stage=self.stage_b, dropoff_stage=self.stage_b2,
            description='ZZB parcel', size='small', receiver_name='ZZB Receiver',
            receiver_phone='+254711900009', price=Decimal('300'))
        self.charter_b = CharterRequest.objects.create(
            passenger=self.pax_b, company=self.b, purpose='ZZB purpose',
            pickup_location='ZZB', destination='ZZB', depart_at=timezone.now() + dt.timedelta(days=3),
            passenger_count=10, contact_name='ZZB', contact_phone='+254711900008')
        self.schedule_b = TripSchedule.objects.create(
            route=self.route_b, driver=self.driver_b, days_of_week='0,1,2',
            departure_time=dt.time(8, 0))
        self.staff_b = mk(username='mgrb', password='pw-123456', phone_number='+254711900002',
                          company=self.b, role='company_manager')
        self.users = {
            'manager': mk(username='mgra', password='pw-123456', phone_number='+254711900003',
                          company=self.a, role='company_manager'),
            'auditor': mk(username='auda', password='pw-123456', phone_number='+254711900004',
                          company=self.a, role='company_auditor'),
            'operator': mk(username='opa', password='pw-123456', phone_number='+254711900005',
                           company=self.a, role='company_operator'),
        }
        scoped = mk(username='opscoped', password='pw-123456', phone_number='+254711900006',
                    company=self.a, role='company_operator', all_routes=False)
        scoped.assigned_routes.add(self.route_a)
        self.users['route-scoped operator'] = scoped

    def snapshot_b(self):
        return (
            list(Company.objects.filter(pk=self.b.pk).values()),
            list(Route.objects.filter(company=self.b).values()),
            list(PickupStage.objects.filter(route=self.route_b).values()),
            list(Driver.objects.filter(company=self.b).values()),
            list(Trip.objects.filter(route=self.route_b).values()),
            list(Booking.objects.filter(route=self.route_b).values()),
            list(Bus.objects.filter(company=self.b).values()),
            list(Parcel.objects.filter(pk=self.parcel_b.pk).values()),
            list(CharterRequest.objects.filter(company=self.b).values()),
            list(TripSchedule.objects.filter(route=self.route_b).values()),
            list(Incident.objects.filter(trip=self.trip_b).values()),
            list(User.objects.filter(pk__in=[self.pax_b.pk, self.staff_b.pk]).values()),
        )


class IdEndpointIsolationTests(MatrixBase):
    """(url name, kwargs from B's objects, methods to try)."""

    def cases(self):
        b = self
        return [
            ('update_company', {'company_id': b.b.id}, ('put', 'patch')),
            ('get_company_routes', {'company_id': b.b.id}, ('get',)),
            ('manage_route', {'route_id': b.route_b.id}, ('put', 'patch', 'delete')),
            ('get_route_pickup_stages', {'route_id': b.route_b.id}, ('get',)),
            ('create_pickup_stage', {'route_id': b.route_b.id}, ('post',)),
            ('route_plan', {'route_id': b.route_b.id}, ('post',)),
            ('route_alternatives', {'route_id': b.route_b.id}, ('post',)),
            ('manage_pickup_stage', {'stage_id': b.stage_b.id}, ('put', 'patch', 'delete')),
            ('approve_pickup_stage', {'stage_id': b.stage_b.id}, ('post',)),
            ('deactivate_pickup_stage', {'stage_id': b.stage_b.id}, ('post',)),
            ('get_company_trips', {'company_id': b.b.id}, ('get',)),
            ('list_schedules', {'company_id': b.b.id}, ('get',)),
            ('list_schedule_generation_exceptions', {'company_id': b.b.id}, ('get',)),
            ('list_weekly_operations_reports', {'company_id': b.b.id}, ('get',)),
            ('manage_schedule', {'schedule_id': b.schedule_b.id}, ('patch', 'delete')),
            ('trip-seat-summary', {'trip_id': b.trip_b.id}, ('get',)),
            ('update_trip_status', {'trip_id': b.trip_b.id}, ('post', 'patch')),
            ('update_trip_capacity', {'trip_id': b.trip_b.id}, ('post', 'patch')),
            ('set_operator_routes', {'user_id': b.staff_b.id}, ('post', 'patch')),
            ('company_analytics', {'company_id': b.b.id}, ('get',)),
            ('users:company-staff-detail', {'staff_id': b.staff_b.id}, ('patch', 'delete')),
            ('bookings:walk-in-booking', {'trip_id': b.trip_b.id}, ('post',)),
            ('bookings:get-booking-detail', {'booking_id': b.booking_b.id}, ('get',)),
            ('bookings:assign-driver', {'booking_id': b.booking_b.id}, ('post',)),
            ('bookings:move-booking-to-trip', {'booking_id': b.booking_b.id}, ('post',)),
            ('bookings:cancel-booking', {'booking_id': b.booking_b.id}, ('post',)),
            ('bookings:verify-boarding', {'booking_id': b.booking_b.id}, ('post',)),
            ('bookings:booking-live-location', {'booking_id': b.booking_b.id}, ('get',)),
            ('bookings:set-stage-departure', {'booking_id': b.booking_b.id}, ('post',)),
            ('bookings:get-driver-bookings', {'driver_id': b.driver_b.id}, ('get',)),
            ('bookings:driver-end-trip', {'driver_id': b.driver_b.id}, ('post',)),
            ('bookings:incident-detail', {'incident_id': b.incident_b.id}, ('get', 'patch')),
            ('bookings:confirm-cash-payment', {'booking_id': b.booking_b.id}, ('post',)),
            ('drivers:driver-detail', {'driver_id': b.driver_b.id}, ('get', 'put', 'patch', 'delete')),
            ('drivers:driver-location', {'driver_id': b.driver_b.id}, ('get', 'post')),
            ('buses:bus-detail', {'bus_id': b.bus_b.id}, ('get', 'put', 'patch', 'delete')),
            ('deliveries:route-rates-update', {'route_id': b.route_b.id}, ('patch',)),
            ('deliveries:parcel-detail', {'parcel_id': b.parcel_b.id}, ('get',)),
            ('deliveries:parcel-verify', {'parcel_id': b.parcel_b.id}, ('post',)),
            ('deliveries:parcel-pickup', {'parcel_id': b.parcel_b.id}, ('post',)),
            ('deliveries:parcel-deliver', {'parcel_id': b.parcel_b.id}, ('post',)),
            ('charters:charter-detail', {'charter_id': b.charter_b.id}, ('get',)),
            ('charters:charter-quote', {'charter_id': b.charter_b.id}, ('post',)),
            ('charters:charter-decline', {'charter_id': b.charter_b.id}, ('post',)),
            ('charters:charter-verify', {'charter_id': b.charter_b.id}, ('post',)),
            ('charters:charter-complete', {'charter_id': b.charter_b.id}, ('post',)),
        ]

    def call(self, client, method, url):
        return getattr(client, method)(url, {}, format='json')

    def test_company_a_staff_cannot_touch_company_b_objects(self):
        from django.urls import reverse
        before = self.snapshot_b()
        failures = []
        for role, user in self.users.items():
            client = APIClient()
            client.force_authenticate(user)
            for name, kwargs, methods in self.cases():
                for method in methods:
                    url = reverse(name, kwargs=kwargs)
                    missing = reverse(name, kwargs={k: 99999999 for k in kwargs})
                    resp = self.call(client, method, url)
                    gone = self.call(client, method, missing)
                    body = resp.content.decode()
                    ok = resp.status_code in (403, 404, 405) or (
                        resp.status_code == 400 and gone.status_code == 400)
                    if not ok or 'ZZB' in body:
                        failures.append(f'{role}: {method.upper()} {name} -> {resp.status_code}'
                                        f'{" LEAK" if "ZZB" in body else ""}')
        self.assertEqual(failures, [])
        self.assertEqual(self.snapshot_b(), before, 'company B data changed')


class ListEndpointIsolationTests(MatrixBase):
    LISTS = (
        'get_trips', 'get_routes', 'route_health', 'operator_route_assignments',
        'users:company-staff', 'bookings:auditor-receipt-search', 'bookings:staff-alerts',
        'bookings:get-all-bookings', 'bookings:incident-list', 'drivers:driver-list',
        'buses:bus-list', 'deliveries:driver-parcels', 'deliveries:company-parcels',
        'deliveries:route-rates', 'charters:charter-company', 'charters:charter-driver',
        'charters:charter-list-create', 'deliveries:parcel-list-create',
        'bookings:passenger-records', 'bookings:get-my-bookings',
    )

    def test_list_endpoints_show_company_a_staff_no_company_b_rows(self):
        from django.urls import reverse
        failures = []
        for role, user in self.users.items():
            client = APIClient()
            client.force_authenticate(user)
            for name in self.LISTS:
                resp = client.get(reverse(name))
                body = resp.content.decode()
                if resp.status_code >= 500 or ('ZZB' in body and name != 'get_routes'):
                    failures.append(f'{role}: GET {name} -> {resp.status_code}')
        self.assertEqual(failures, [])

    def test_company_filter_params_cannot_widen_the_scope(self):
        from django.urls import reverse
        client = APIClient()
        client.force_authenticate(self.users['manager'])
        for name in ('get_trips', 'drivers:driver-list', 'buses:bus-list',
                     'bookings:get-all-bookings', 'bookings:incident-list'):
            resp = client.get(reverse(name), {'company_id': self.b.id, 'company': self.b.id})
            self.assertNotIn('ZZB', resp.content.decode(), name)
