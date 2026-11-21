from datetime import timedelta

from django.conf import settings
from django.db import migrations
from django.db.models import F, OuterRef, Subquery
from django.utils import timezone

# Rows already past their hold keep it this much longer, so a payment that is
# in flight at deploy time can still be confirmed before the sweep cancels them.
GRACE_FOR_EXPIRED = timedelta(minutes=2)


def backfill_held_until(apps, schema_editor):
    """Set held_until on every pending booking (single UPDATEs, no Python loop).

    Rows that are not pending are left NULL. A pending booking that is already
    past its hold is given now + 2 minutes; the next sweep then cancels it.
    """
    Booking = apps.get_model('bookings', 'Booking')
    Trip = apps.get_model('companies', 'Trip')

    hold = timedelta(minutes=getattr(settings, 'PAYMENT_HOLD_MINUTES', 10))
    cash_hold = timedelta(
        minutes=getattr(settings, 'CASH_PENDING_TTL_MINUTES', 20))

    pending = Booking.objects.filter(status='pending', held_until__isnull=True)
    pending.exclude(payment__method='cash').update(
        held_until=F('created_at') + hold)
    pending.filter(payment__method='cash').update(
        held_until=F('created_at') + cash_hold)

    # A hold never outlives the departure. Done separately because Least()
    # ignores NULLs on Postgres but returns NULL on SQLite.
    Booking.objects.filter(
        status='pending', trip__isnull=False,
        held_until__gt=F('trip__departure_at'),
    ).update(held_until=Subquery(
        Trip.objects.filter(pk=OuterRef('trip_id')).values('departure_at')[:1]
    ))

    now = timezone.now()
    Booking.objects.filter(status='pending', held_until__lte=now).update(
        held_until=now + GRACE_FOR_EXPIRED)


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0029_booking_held_until'),
    ]

    operations = [
        migrations.RunPython(backfill_held_until, migrations.RunPython.noop),
    ]
