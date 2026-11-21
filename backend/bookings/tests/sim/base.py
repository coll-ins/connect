"""Shared setup for the world simulation: a TransactionTestCase base class and helpers.

TransactionTestCase flushes every table after each test, which would delete the
SACCOs and routes the migrations seed. `serialized_rollback = True` makes Django
restore them before each test, so the simulation runs against the real seeded
Company and Route rows (never a hand-made copy).
"""
import datetime as dt
import itertools
import random
import threading
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from bookings.models import Booking, Payment
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

from . import fake_gateway as fg
from . import route_fixtures
from .invariants import assert_world_invariants

User = get_user_model()
POSTGRES = connection.vendor == 'postgresql'
LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
HIGH = '1000000/minute'
RATES = {k: HIGH for k in (
    'anon', 'user', 'signup', 'driver_location', 'boarding_verify', 'login_ip',
    'bus_reroute', 'mpesa_push')}
PASSWORD = 'Sim-pass-2026-xyz'
SEED = 20261120


class SimCase(TransactionTestCase):
    serialized_rollback = True
    # Set to False by a test that must not run the end-of-test sweeps.
    settle_at_end = True

    def setUp(self):
        super().setUp()
        self.enterContext(override_settings(
            CACHES=LOCMEM, WALLET_TOPUP_ENABLED=True, WALLET_PAYOUTS_ENABLED=True,
            # These worlds test the 50% passenger-cancel rule; a cancel before
            # the change cut-off is a full refund (tested in test_change_cutoff).
            BOOKING_CHANGE_CUTOFF_MINUTES=60 * 24 * 365))
        self.enterContext(mock.patch(
            'users.models.CustomUser.can_pay_cash', new=True))
        cache.clear()
        self.enterContext(mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, RATES))
        from wallets.throttles import TopUpThrottle, WithdrawThrottle
        self.enterContext(mock.patch.object(TopUpThrottle, 'rate', HIGH))
        self.enterContext(mock.patch.object(WithdrawThrottle, 'rate', HIGH))
        self.fake = fg.FakePaystack().install(self)
        self.rng = random.Random(SEED)
        self._phones = itertools.count(10_000_000)
        self._staff = {}
        # A silently empty database (serialized_rollback not restoring) must
        # never pass: every scenario runs on the migration-seeded data.
        self.assertGreaterEqual(Route.objects.count(), 35)
        self.assertGreaterEqual(Company.objects.count(), 3)
        # Registered last, so it runs first on cleanup while the fake, the
        # cache override and the throttle patch are all still active.
        self.addCleanup(self._final_invariants)

    def _final_invariants(self):
        assert_world_invariants(self, settle=self.settle_at_end)

    # ------------------------------------------------------------ people
    def phone(self):
        return f'+2547{next(self._phones):08d}'

    def user(self, role='passenger', company=None, name=None, phone=None, **extra):
        phone = phone or self.phone()
        return User.objects.create_user(
            username=name or f'sim{role[:4]}{phone[-8:]}', password=PASSWORD,
            phone_number=phone, role=role, company=company, **extra)

    def staff(self, company, role='company_manager'):
        key = (company.pk, role)
        if key not in self._staff:
            self._staff[key] = self.user(role, company)
        return self._staff[key]

    def driver(self, company, bus=None):
        """A Driver row plus the login account that is_driver_account_for accepts."""
        phone = self.phone()
        number = bus or f'KSM {next(self._phones) % 1000:03d}S'
        driver = Driver.objects.create(
            name=f'Driver {number}', phone_number=phone, bus_number=number, company=company)
        account = self.user('driver', company, phone=phone)
        driver.account = account
        return driver

    @staticmethod
    def api(user):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client

    # ------------------------------------------------------------ world data
    def companies(self):
        return list(Company.objects.order_by('id'))

    def routes_of(self, company):
        return list(Route.objects.filter(company=company).order_by('id'))

    def add_stages(self, route, index=0, count=3):
        return route_fixtures.install(route, index, count)

    def trip(self, route, driver=None, minutes=60, capacity=14, status='scheduled'):
        driver = driver or self.driver(route.company)
        return Trip.objects.create(
            route=route, driver=driver, capacity=capacity, status=status,
            departure_at=timezone.now() + dt.timedelta(minutes=minutes))

    def first_stage(self, route):
        return route.pickup_stages.filter(is_active=True).order_by('order', 'id').first()

    def ready_route(self, company_index=0, route_index=0, index=0):
        """A seeded route with synthetic stages: (company, route)."""
        company = self.companies()[company_index]
        route = self.routes_of(company)[route_index]
        if not route.pickup_stages.exists():
            self.add_stages(route, index)
        return company, route

    # ------------------------------------------------------------ bookings
    def book(self, user, trip, seats=1, stage=None, expect=201, **extra):
        stage = stage or self.first_stage(trip.route)
        body = {'trip_id': trip.pk, 'seats': seats, 'pickup_stage_id': stage.pk, **extra}
        response = self.api(user).post(reverse('bookings:create-booking'), body, format='json')
        self.assertEqual(response.status_code, expect, response.content)
        return response.json()

    def booking(self, user, trip, seats=1, **kw):
        data = self.book(user, trip, seats, **kw)
        return Booking.objects.get(pk=data['booking_id'] if 'booking_id' in data else data['id'])

    def init_digital(self, user, booking, mpesa=False, expect=200, **extra):
        name = 'bookings:initialize-mpesa-payment' if mpesa else 'bookings:initialize-paystack-payment'
        response = self.api(user).post(reverse(name, args=[booking.pk]), extra, format='json')
        self.assertEqual(response.status_code, expect, response.content)
        return response.json().get('reference')

    def webhook(self, event, **kw):
        return fg.post_event(Client(), event, **kw)

    def pay(self, user, booking, amount=None, mpesa=True, deliver=True):
        """Checkout then the customer pays `amount` (default: exactly the fare)."""
        reference = self.init_digital(user, booking, mpesa=mpesa)
        amount = booking.total_amount if amount is None else amount
        event = self.fake.customer_pays(
            reference, amount, metadata={'booking_id': booking.pk, 'user_id': user.pk})
        response = self.webhook(event) if deliver else None
        return reference, event, response

    def cancel(self, user, booking, fault=None, expect=200):
        body = {'fault_party': fault} if fault else {}
        response = self.api(user).post(reverse('bookings:cancel-booking', args=[booking.pk]), body, format='json')
        self.assertEqual(response.status_code, expect, response.content)
        return response.json()

    def confirmed_booking(self, user, trip, seats=1, amount=None):
        booking = self.booking(user, trip, seats)
        reference, event, response = self.pay(user, booking, amount)
        self.assertEqual(response.status_code, 200)
        booking.refresh_from_db()
        return booking, reference

    # ------------------------------------------------------------ time travel
    def expire_hold(self, booking, seconds_ago=1):
        Booking.objects.filter(pk=booking.pk).update(
            held_until=timezone.now() - dt.timedelta(seconds=seconds_ago))

    def depart_in(self, trip, minutes):
        Trip.objects.filter(pk=trip.pk).update(
            departure_at=timezone.now() + dt.timedelta(minutes=minutes))

    # ------------------------------------------------------------ concurrency
    def run_threads(self, jobs):
        """Run callables at the same instant. Returns (results, errors); errors must be []."""
        barrier = threading.Barrier(len(jobs))
        results, errors = [None] * len(jobs), []

        def go(i, job):
            try:
                barrier.wait()
                results[i] = job()
            except Exception as exc:
                errors.append(f'{type(exc).__name__}: {exc}')
            finally:
                connection.close()

        threads = [threading.Thread(target=go, args=(i, j)) for i, j in enumerate(jobs)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results, errors

    # ------------------------------------------------------------ misc
    def alerts(self, containing=''):
        return [m for m, _, label, _ in self.fake.sms if label == 'admin-alert' and containing in m]

    def payment(self, booking):
        return Payment.objects.get(booking=booking)

    def run_command(self, name, *args):
        from io import StringIO
        out, err = StringIO(), StringIO()
        call_command(name, *args, stdout=out, stderr=err)
        return out.getvalue() + err.getvalue()

    def stage_count(self, route):
        return PickupStage.objects.filter(route=route).count()

    def money(self, value):
        return Decimal(str(value)).quantize(Decimal('0.01'))
