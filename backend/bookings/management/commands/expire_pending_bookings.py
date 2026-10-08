"""
Cancel unpaid pending bookings that have been open longer than
PENDING_BOOKING_TTL_MINUTES, so abandoned checkouts stop holding seats.
Run from cron every 5 minutes.

Safe against races: each booking row is locked first. If a payment webhook
confirmed it a moment earlier, it is no longer 'pending' and is skipped; if
this command wins, a late payment is refunded by the existing late-payment path.
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import OperationalError, transaction
from django.utils import timezone

from bookings.models import Booking, Payment


class Command(BaseCommand):
    help = 'Cancel abandoned pending bookings and free their seats.'

    def add_arguments(self, parser):
        parser.add_argument('--ttl-minutes', type=int, default=None)

    def handle(self, *args, **options):
        ttl = options['ttl_minutes'] or getattr(settings, 'PENDING_BOOKING_TTL_MINUTES', 20)
        cutoff = timezone.now() - timedelta(minutes=ttl)

        candidate_ids = list(
            Booking.objects
            .filter(status='pending', created_at__lt=cutoff, trip__status='scheduled')
            .values_list('pk', flat=True)
        )

        cancelled = 0
        for pk in candidate_ids:
            try:
                with transaction.atomic():
                    # No select_related: Booking.trip is nullable (see confirm_cash_payment).
                    booking = Booking.objects.select_for_update().get(pk=pk)
                    if booking.status != 'pending':
                        continue
                    if Payment.objects.filter(booking=booking, status='confirmed').exists():
                        continue
                    booking.status = 'cancelled'
                    booking.save(update_fields=['status'])
                    cancelled += 1
            except OperationalError:
                # Lock conflict with a payment in flight: leave it for the next run.
                continue

        self.stdout.write(f'expire_pending_bookings: cancelled {cancelled}')
