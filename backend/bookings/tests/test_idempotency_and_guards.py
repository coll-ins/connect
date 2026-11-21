"""create_booking idempotency key, tampered amounts, Payment reuse (BE-1b)."""
import datetime as dt
import threading
import unittest
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking, Payment
from bookings.tests.test_late_payments import MoneyBase
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()


class IdempotencyKeyTests(MoneyBase):
    def create(self, key='k-1', **extra):
        self.client.force_authenticate(self.passenger)
        body = {'trip_id': self.trip.id, 'seats': 1,
                'pickup_stage_id': self.stage.id, 'idempotency_key': key}
        body.update(extra)
        return self.client.post('/api/bookings/create/', body, format='json')

    def test_idempotency_key_replay(self):
        first = self.create()
        second = self.create()
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(second.data['booking_id'], first.data['booking_id'])
        self.assertEqual(second.data['booking_number'], first.data['booking_number'])
        self.assertTrue(second.data['replayed'])
        self.assertEqual(Booking.objects.count(), 1)

    def test_replay_still_answers_when_the_first_booking_filled_the_cap(self):
        self.create('a')
        self.create('b')
        self.create('c')
        again = self.create('a')
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(Booking.objects.count(), 3)

    def test_replay_after_cutoff_returns_the_original(self):
        first = self.create()
        Trip.objects.filter(pk=self.trip.pk).update(
            departure_at=timezone.now() + dt.timedelta(minutes=5))
        again = self.create()
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(again.data['booking_id'], first.data['booking_id'])

    def test_same_key_for_a_different_request_is_refused(self):
        self.create()
        other = self.create(seats=2)
        self.assertEqual(other.status_code, 409, other.content)
        self.assertEqual(other.data['code'], 'idempotency_key_reused')
        self.assertEqual(Booking.objects.count(), 1)

    def test_keys_are_per_user(self):
        self.create()
        self.client.force_authenticate(self.user())
        resp = self.client.post('/api/bookings/create/', {
            'trip_id': self.trip.id, 'seats': 1,
            'pickup_stage_id': self.stage.id, 'idempotency_key': 'k-1'},
            format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(Booking.objects.count(), 2)

    def test_no_key_keeps_the_old_behaviour(self):
        self.client.force_authenticate(self.passenger)
        body = {'trip_id': self.trip.id, 'seats': 1, 'pickup_stage_id': self.stage.id}
        self.assertEqual(self.client.post('/api/bookings/create/', body, format='json').status_code, 201)
        self.assertEqual(self.client.post('/api/bookings/create/', body, format='json').status_code, 201)
        self.assertEqual(Booking.objects.count(), 2)

    def test_bad_key_is_a_400(self):
        for key in ('x' * 65, 'has space', 'semi;colon'):
            self.assertEqual(self.create(key).status_code, 400, key)
        self.assertEqual(Booking.objects.count(), 0)

    def test_blank_key_counts_as_no_key(self):
        self.assertEqual(self.create('').status_code, 201)
        self.assertEqual(self.create('').status_code, 201)
        self.assertEqual(Booking.objects.count(), 2)


class TamperedAmountTests(MoneyBase):
    def test_tampered_amount_rejected_on_every_init(self):
        booking = self.booking(1, 'pending', timezone.now() + dt.timedelta(minutes=5),
                               user=self.passenger)
        self.client.force_authenticate(self.passenger)
        for url, extra in (
            (f'/api/bookings/payments/{booking.id}/paystack/', {}),
            (f'/api/bookings/payments/{booking.id}/mpesa/', {'phone_number': '+254711222222'}),
            (f'/api/bookings/payments/{booking.id}/cash/', {}),
        ):
            for field in ('amount', 'total_amount'):
                resp = self.client.post(url, {**extra, field: '1'}, format='json')
                self.assertEqual(resp.status_code, 400, (url, resp.content))
                self.assertEqual(resp.data['code'], 'amount_mismatch')
                self.assertEqual(resp.data['expected'], '100.00')
            resp = self.client.post(url, {**extra, 'amount': 'abc'}, format='json')
            self.assertEqual(resp.status_code, 400, url)
        self.assertFalse(Payment.objects.filter(booking=booking).exists())
        self.assertEqual(self.gateway.refunds, [])

    def test_a_matching_amount_is_accepted(self):
        booking = self.booking(1, 'pending', timezone.now() + dt.timedelta(minutes=5),
                               user=self.passenger)
        self.client.force_authenticate(self.passenger)
        resp = self.client.post(
            f'/api/bookings/payments/{booking.id}/cash/', {'amount': '100'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_create_booking_rejects_a_tampered_total(self):
        self.client.force_authenticate(self.passenger)
        resp = self.client.post('/api/bookings/create/', {
            'trip_id': self.trip.id, 'seats': 2, 'total_amount': '1',
            'pickup_stage_id': self.stage.id}, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.data['code'], 'amount_mismatch')
        self.assertEqual(resp.data['expected'], '200.00')
        self.assertEqual(Booking.objects.count(), 0)


class PaymentReuseResetTests(MoneyBase):
    def test_reinitiating_a_failed_payment_clears_the_refund_fields(self):
        booking = self.booking(1, 'pending', timezone.now() + dt.timedelta(minutes=5),
                               user=self.passenger)
        self.client.force_authenticate(self.passenger)
        for suffix, extra in (('paystack', {}), ('mpesa', {'phone_number': '+254711222222'}),
                              ('cash', {})):
            Payment.objects.filter(booking=booking).delete()
            pay = Payment.objects.create(
                booking=booking, amount=Decimal('100'), method='digital',
                status='failed', refund_reason='late_payment',
                paid_amount=Decimal('150'))
            resp = self.client.post(
                f'/api/bookings/payments/{booking.id}/{suffix}/', extra, format='json')
            self.assertIn(resp.status_code, (200, 201), (suffix, resp.content))
            pay.refresh_from_db()
            self.assertEqual((pay.refund_reason, pay.paid_amount), ('', None), suffix)


@unittest.skipUnless(connection.vendor == 'postgresql', 'needs real row locks')
class DoubleSubmitRaceTests(TransactionTestCase):
    def test_eight_simultaneous_submits_make_one_booking(self):
        company = Company.objects.create(name='Idem Co', areas_served='Nairobi')
        route = Route.objects.create(
            company=company, name='CBD - Ngong', start_point='CBD',
            end_point='Ngong', price=Decimal('100'))
        stage = PickupStage.objects.create(
            route=route, name='Kencom', order=1,
            latitude=Decimal('-1.2856'), longitude=Decimal('36.8250'))
        driver = Driver.objects.create(
            name='D', phone_number='+254711000000', bus_number='KDA 001A',
            company=company)
        trip = Trip.objects.create(
            route=route, driver=driver, capacity=14, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=3))
        user = User.objects.create_user(
            username='dbl', password='pw-123456', phone_number='+254711555555')
        barrier = threading.Barrier(8)
        codes = []

        def submit():
            client = APIClient()
            client.force_authenticate(user)
            barrier.wait()
            try:
                r = client.post('/api/bookings/create/', {
                    'trip_id': trip.id, 'seats': 1, 'pickup_stage_id': stage.id,
                    'idempotency_key': 'tap-1'}, format='json')
                codes.append(r.status_code)
            finally:
                connection.close()

        threads = [threading.Thread(target=submit) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(codes), [200] * 7 + [201], codes)
        self.assertEqual(Booking.objects.filter(user=user).count(), 1)
