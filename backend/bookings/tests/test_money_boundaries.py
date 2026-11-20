"""Guards pinned at their exact boundary, so loosening one by a unit fails a test."""
import datetime as dt
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from bookings import services
from bookings.models import Incident, Payment, UnappliedPayment
from bookings.tests.review_base import WorldMixin
from bookings.tests.sim import fake_gateway as fg
from companies.models import Trip


def charge(reference, subunits, currency='KES'):
    return {'event': 'charge.success', 'data': {
        'reference': reference, 'amount': subunits, 'currency': currency, 'status': 'success'}}


class PendingDigitalMixin(WorldMixin):
    def pending_digital(self, held_for=dt.timedelta(minutes=5)):
        b = self.booking(self.pax, self.trip1, 1, 'pending', held_until=timezone.now() + held_for)
        ref = f'CONNECT-{b.id}-' + 'a' * 32
        pay = Payment.objects.create(booking=b, amount=Decimal('100'), method='digital',
                                     status='pending', provider_reference=ref)
        return b, pay, ref

    def hook(self, ref, subunits):
        return fg.post_event(APIClient(), charge(ref, subunits))


class UnderpaymentBoundaryTests(PendingDigitalMixin, TestCase):
    def test_one_subunit_short_is_rejected_for_review(self):
        b, pay, ref = self.pending_digital()
        self.assertEqual(self.hook(ref, 9999).status_code, 200)
        b.refresh_from_db()
        pay.refresh_from_db()
        self.assertEqual((pay.status, b.status), ('failed', 'pending'))
        row = UnappliedPayment.objects.get(reference=ref)
        self.assertEqual((row.status, row.amount), ('review', Decimal('99.99')))
        self.assertEqual(self.fake.accepted_refunds(ref), [])

    def test_exactly_the_expected_amount_is_accepted(self):
        b, pay, ref = self.pending_digital()
        self.assertEqual(self.hook(ref, 10000).status_code, 200)
        b.refresh_from_db()
        pay.refresh_from_db()
        self.assertEqual((pay.status, b.status), ('confirmed', 'confirmed'))
        self.assertFalse(UnappliedPayment.objects.filter(reference=ref).exists())

    def test_one_subunit_over_is_accepted_and_the_difference_is_owed_back(self):
        b, pay, ref = self.pending_digital()
        self.assertEqual(self.hook(ref, 10001).status_code, 200)
        pay.refresh_from_db()
        self.assertEqual(pay.status, 'confirmed')
        row = UnappliedPayment.objects.get(reference=ref)
        self.assertEqual((row.reason, row.amount), ('overpayment', Decimal('0.01')))
        self.assertEqual(row.status, 'review')


class ProcessingRefundClaimTests(WorldMixin, TestCase):
    def test_second_claim_on_processing_refund_is_refused(self):
        b = self.booking(self.pax, self.trip1, 1, 'confirmed')
        Payment.objects.create(
            booking=b, amount=Decimal('100'), method='digital', status='confirmed',
            provider_reference='CONNECT-9-' + 'd' * 32, refund_status='processing',
            refund_amount=Decimal('50.00'))
        amount, claim = services.claim_booking_refund(b, 'company')
        self.assertIsNone(claim)
        self.assertEqual(amount, Decimal('50.00'))

    def test_a_confirmed_payment_with_no_refund_in_flight_is_claimed_once(self):
        b = self.booking(self.pax, self.trip1, 1, 'confirmed')
        Payment.objects.create(
            booking=b, amount=Decimal('100'), method='digital', status='confirmed',
            provider_reference='CONNECT-9-' + 'd' * 32)
        amount, claim = services.claim_booking_refund(b, 'company')
        self.assertIsNotNone(claim)
        self.assertEqual(amount, Decimal('100.00'))
        again_amount, again = services.claim_booking_refund(b, 'company')
        self.assertIsNone(again)


@override_settings(PAYMENT_ARRIVAL_TOLERANCE_SECONDS=60)
class SweepToleranceTests(PendingDigitalMixin, TestCase):
    def sweep(self):
        call_command('expire_pending_bookings', stdout=StringIO(), stderr=StringIO())

    def test_hold_inside_the_tolerance_is_not_cancelled_by_the_sweep(self):
        b, pay, ref = self.pending_digital(held_for=-dt.timedelta(seconds=30))
        self.sweep()
        b.refresh_from_db()
        self.assertEqual(b.status, 'pending')

    def test_a_charge_arriving_after_the_sweep_but_inside_the_tolerance_confirms(self):
        b, pay, ref = self.pending_digital(held_for=-dt.timedelta(seconds=30))
        self.sweep()
        self.assertEqual(self.hook(ref, 10000).status_code, 200)
        b.refresh_from_db()
        self.assertEqual(b.status, 'confirmed')

    def test_hold_past_the_tolerance_is_cancelled_by_the_sweep(self):
        b, pay, ref = self.pending_digital(held_for=-dt.timedelta(seconds=90))
        self.sweep()
        b.refresh_from_db()
        self.assertEqual(b.status, 'cancelled')

    def test_the_seat_is_free_from_held_until_even_before_the_sweep_cancels(self):
        b, pay, ref = self.pending_digital(held_for=-dt.timedelta(seconds=30))
        self.assertEqual(services.seats_taken(self.trip1), 0)


class RescheduleCutoffTests(WorldMixin, TestCase):
    """resolve-incident reschedule is exempt from the booking cut-off on purpose."""

    def test_reschedule_onto_a_trip_inside_the_cutoff_is_allowed(self):
        self.co.booking_cutoff_minutes = 60
        self.co.save()
        b = self.booking(self.pax, self.trip1)
        Payment.objects.create(booking=b, amount=Decimal('100'), method='cash', status='confirmed')
        Incident.objects.create(trip=self.trip1, reported_by=self.mgr, incident_type='breakdown',
                                description='x', status='reported')
        soon = Trip.objects.create(route=self.r1, driver=self.drv2, capacity=14, status='scheduled',
                                   departure_at=timezone.now() + dt.timedelta(minutes=20))
        self.assertLess(services.booking_closes_at(soon), timezone.now())
        r = self.api(self.pax).post(f'/api/bookings/{b.id}/resolve-incident/', {
            'resolution': 'reschedule', 'replacement_trip_id': soon.id}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:300])
        b.refresh_from_db()
        self.assertEqual(b.trip_id, soon.id)

    def test_reschedule_onto_a_trip_that_already_left_is_still_refused(self):
        b = self.booking(self.pax, self.trip1)
        Payment.objects.create(booking=b, amount=Decimal('100'), method='cash', status='confirmed')
        Incident.objects.create(trip=self.trip1, reported_by=self.mgr, incident_type='breakdown',
                                description='x', status='reported')
        gone = Trip.objects.create(route=self.r1, driver=self.drv2, capacity=14, status='scheduled',
                                   departure_at=timezone.now() - dt.timedelta(minutes=5))
        r = self.api(self.pax).post(f'/api/bookings/{b.id}/resolve-incident/', {
            'resolution': 'reschedule', 'replacement_trip_id': gone.id}, format='json')
        self.assertEqual(r.status_code, 409, r.content[:300])
