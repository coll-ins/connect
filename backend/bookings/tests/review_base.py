"""Shared fixtures for the review-round tests (not a test module itself).

WorldMixin installs the fake gateway in every test, so nothing here can reach
Paystack or the SMS provider, and fails the test if anything tried to.
"""
import datetime as dt
import threading
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking
from bookings.tests.sim import fake_gateway as fg
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()
PG = connection.vendor == 'postgresql'


class WorldMixin:
    def setUp(self):
        super().setUp()
        # Cash on board is gated to proven riders upstream; these tests are
        # about seats and money, so the gate is open.
        patcher = mock.patch('users.models.CustomUser.can_pay_cash', new=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake = fg.FakePaystack().install(self)
        self.addCleanup(lambda: self.assertEqual(self.fake.leaks, []))
        self.co = Company.objects.create(name='SB Co', areas_served='Nairobi')
        self.co2 = Company.objects.create(name='SB Co2', areas_served='Nairobi')
        self.r1 = Route.objects.create(company=self.co, name='R1', start_point='A', end_point='B', price=Decimal('100'))
        self.r2 = Route.objects.create(company=self.co, name='R2', start_point='C', end_point='D', price=Decimal('100'))
        self.s1 = PickupStage.objects.create(route=self.r1, name='S1', order=1, latitude=Decimal('-1.28'), longitude=Decimal('36.82'))
        self.s2 = PickupStage.objects.create(route=self.r2, name='S2', order=1, latitude=Decimal('-1.28'), longitude=Decimal('36.82'))
        self.drv = Driver.objects.create(name='D', phone_number='+254711000000', bus_number='KDA 001A', company=self.co)
        self.drv2 = Driver.objects.create(name='D2', phone_number='+254711000001', bus_number='KDA 002A', company=self.co)
        mk = User.objects.create_user
        self.mgr = mk(username='mgr', password='pw-123456', phone_number='+254722000001', role='company_manager', company=self.co)
        self.op_all = mk(username='opall', password='pw-123456', phone_number='+254722000002', role='company_operator', company=self.co)
        self.op_r2 = mk(username='opr2', password='pw-123456', phone_number='+254722000003', role='company_operator', company=self.co, all_routes=False)
        self.op_r2.assigned_routes.add(self.r2)
        self.pax = mk(username='pax', password='pw-123456', phone_number='+254733000001')
        self.pax2 = mk(username='pax2', password='pw-123456', phone_number='+254733000002')
        self.trip1 = Trip.objects.create(route=self.r1, driver=self.drv, capacity=14, status='boarding',
                                         departure_at=timezone.now() + dt.timedelta(minutes=30))

    def passenger(self):
        self._pax_n = getattr(self, '_pax_n', 0) + 1
        return User.objects.create_user(
            username=f'sc{self._pax_n}', password='pw-123456',
            phone_number=f'+2547118{self._pax_n:05d}', role='passenger')

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def booking(self, user, trip, seats=1, status='confirmed', held_until=None, route=None, stage=None):
        route = route or trip.route
        return Booking.objects.create(
            user=user, trip=trip, route=route, driver=trip.driver, seats=seats,
            total_amount=route.price * seats, status=status, held_until=held_until,
            pickup_location='S', pickup_stage=stage or route.pickup_stages.first())


def run_together(jobs):
    """Run jobs at the same instant. Returns (results, errors); a crash is an error, never a result."""
    barrier = threading.Barrier(len(jobs))
    out, errs = [None] * len(jobs), []

    def go(i, job):
        try:
            barrier.wait()
            out[i] = job()
        except Exception as exc:  # noqa: BLE001  collected and asserted empty by the caller
            errs.append(f'{type(exc).__name__}: {exc}')
        finally:
            connection.close()

    threads = [threading.Thread(target=go, args=(i, j)) for i, j in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out, errs


def fund(user, amount, ref):
    from wallets import services
    with transaction.atomic():
        services.credit(user, Decimal(str(amount)), 'deposit', ref)
