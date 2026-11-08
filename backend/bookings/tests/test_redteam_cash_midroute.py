import datetime as dt

from django.core.management import call_command
from django.utils import timezone

from bookings.models import Booking, Payment
from bookings.tests.test_boarding_stage_flow import Base


class CashMidRouteBreakerTests(Base):
    def setUp(self):
        super().setUp()
        self.booking = self._booking(1, status='pending')
        Payment.objects.create(
            booking=self.booking, amount=self.booking.total_amount,
            method='cash', status='pending',
        )

    def test_departure_sweep_must_not_cancel_cash_pending_booking(self):
        # process_noshows cancels every pending booking when the trip departs,
        # so a mid-route cash passenger loses the seat/PIN the feature promises.
        type(self.trip).objects.filter(pk=self.trip.pk).update(
            status='boarding', departure_at=timezone.now() - dt.timedelta(minutes=5),
        )
        call_command('process_noshows')
        self.assertEqual(Booking.objects.get(pk=self.booking.pk).status, 'pending')
