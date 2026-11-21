"""
Cancel unpaid pending bookings whose hold (held_until) has run out. A hold is
PAYMENT_HOLD_MINUTES, or CASH_PENDING_TTL_MINUTES for a pay-at-stage booking.
This is cleanup: seats_taken() already ignores an expired hold, so seats are
free whether or not this runs. Run from cron every 5 minutes.

Safe against races: each booking row is locked first. If a payment webhook
confirmed it a moment earlier, it is no longer 'pending' and is skipped; if
this command wins, a late payment is refunded by the existing late-payment path.
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import OperationalError, transaction
from django.db.models import Q
from django.utils import timezone

from bookings.models import Booking, Payment
from bookings.services import cancel_dead_pending_bookings


class Command(BaseCommand):
    help = 'Cancel abandoned pending bookings and free their seats.'

    def add_arguments(self, parser):
        parser.add_argument('--ttl-minutes', type=int, default=None)

    def handle(self, *args, **options):
        now = timezone.now()
        ttl = options['ttl_minutes']
        # Seats free at held_until, but the booking is only cancelled once
        # the arrival tolerance has passed, so a charge landing just after
        # the hold still confirms if the seat is free.
        tolerance = timedelta(
            seconds=getattr(settings, 'PAYMENT_ARRIVAL_TOLERANCE_SECONDS', 60))

        if ttl:
            # Explicit override: judge by age, ignoring held_until.
            expired = Q(created_at__lt=now - timedelta(minutes=ttl))
        else:
            hold = getattr(settings, 'PAYMENT_HOLD_MINUTES', 10)
            expired = Q(held_until__lte=now - tolerance) | Q(
                # Row written without a hold (old code during a deploy).
                held_until__isnull=True,
                created_at__lt=now - timedelta(minutes=hold),
            )

        candidate_ids = list(
            Booking.objects
            .filter(expired, status='pending', trip__status__in=['scheduled', 'boarding'])
            # Cash is paid to the conductor on boarding, so waiting is not abandonment.
            # Departed trips still clear it via cancel_dead_pending_bookings below.
            .exclude(payment__method='cash')
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
                    if not ttl and booking.held_until is not None and booking.held_until > now - tolerance:
                        continue
                    if Payment.objects.filter(booking=booking, status='confirmed').exists():
                        continue
                    booking.status = 'cancelled'
                    booking.save(update_fields=['status'])
                    cancelled += 1
            except OperationalError:
                # Lock conflict with a payment in flight: leave it for the next run.
                continue

        cancelled += cancel_dead_pending_bookings(Booking.objects.all())

        self.stdout.write(f'expire_pending_bookings: cancelled {cancelled}')
