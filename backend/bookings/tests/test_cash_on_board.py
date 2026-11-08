import datetime as dt

from django.utils import timezone

from bookings.models import Booking, Payment
from bookings.tests.test_boarding_stage_flow import Base


class CashOnBoardTests(Base):
    """Cash is paid to the driver on boarding, possibly at a later stage."""

    def setUp(self):
        super().setUp()
        self.booking = self._booking(1, status='pending')
        Payment.objects.create(
            booking=self.booking, amount=self.booking.total_amount,
            method='cash', status='pending',
        )

    def _my_booking(self):
        self.client.force_authenticate(user=self.passenger)
        rows = self.client.get('/api/bookings/my/').json()
        return next(r for r in rows if r['booking_id'] == self.booking.id)

    def test_pin_is_shown_before_the_cash_is_paid(self):
        self.assertEqual(self._my_booking()['verification_pin'], self.booking.verification_pin)

    def test_departed_trip_keeps_the_cash_booking_and_takes_the_cash(self):
        Trip = type(self.trip)
        Trip.objects.filter(pk=self.trip.pk).update(
            status='departed', departure_at=timezone.now() - dt.timedelta(minutes=30),
        )
        row = self._my_booking()
        self.assertEqual(row['status'], 'pending')
        self.assertEqual(row['verification_pin'], self.booking.verification_pin)

        self.client.force_authenticate(user=self.manager)
        res = self.client.post(f'/api/bookings/payments/{self.booking.id}/cash/confirm/')
        self.assertEqual(res.status_code, 200, res.content)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')

    def test_unpaid_digital_booking_still_has_no_pin(self):
        Payment.objects.filter(booking=self.booking).update(method='digital')
        self.assertIsNone(self._my_booking()['verification_pin'])

    def test_finished_trip_cannot_take_cash(self):
        type(self.trip).objects.filter(pk=self.trip.pk).update(status='completed')
        self.client.force_authenticate(user=self.manager)
        res = self.client.post(f'/api/bookings/payments/{self.booking.id}/cash/confirm/')
        self.assertNotEqual(res.status_code, 200)
        self.assertEqual(Booking.objects.get(pk=self.booking.pk).payment.status, 'pending')


class OpenIssueFixTests(CashOnBoardTests):
    def _depart(self, minutes_ago):
        type(self.trip).objects.filter(pk=self.trip.pk).update(
            status='departed', departure_at=timezone.now() - dt.timedelta(minutes=minutes_ago),
        )

    def test_unpaid_cash_passenger_sees_the_bus_but_not_the_driver_phone(self):
        self._depart(5)
        self.client.force_authenticate(user=self.passenger)
        res = self.client.get(f'/api/bookings/{self.booking.id}/live-location/')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertFalse(res.json()['contacts_visible'])
        self.assertNotIn(self.driver.phone_number, res.content.decode())

    def test_a_trip_nobody_ended_stops_taking_cash(self):
        self._depart(13 * 60)
        self.client.force_authenticate(user=self.manager)
        res = self.client.post(f'/api/bookings/payments/{self.booking.id}/cash/confirm/')
        self.assertNotEqual(res.status_code, 200)

    def test_departure_sweep_only_no_shows_the_first_stage(self):
        from django.core.management import call_command
        from io import StringIO
        later = self._booking(1, status='confirmed')
        later.pickup_stage = self.stage2
        later.save(update_fields=['pickup_stage'])
        first = self._booking(1, status='confirmed')
        for b in (later, first):
            Payment.objects.create(booking=b, amount=b.total_amount, method='cash', status='confirmed')
        self._depart(30)
        call_command('process_noshows', stdout=StringIO(), stderr=StringIO())
        self.assertEqual(Booking.objects.get(pk=later.pk).status, 'confirmed')
        self.assertEqual(Booking.objects.get(pk=first.pk).status, 'no_show')
