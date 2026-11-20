from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from companies.models import Trip
from bookings.models import Payment
from bookings.services import (
    _alert_admin,
    claim_booking_refund,
    run_refund_claims,
    settle_booking_fault,
)


# Passengers are only treated as no-shows this long after departure.
GRACE_PERIOD = timedelta(minutes=15)

# A refund Paystack keeps refusing is retried after 10 min, 30 min, 2 h, 6 h,
# 24 h and then daily; after REFUND_RETRY_CAP tries a human takes over.
REFUND_RETRY_DELAYS = (
    timedelta(minutes=10), timedelta(minutes=30), timedelta(hours=2),
    timedelta(hours=6), timedelta(hours=24),
)
REFUND_RETRY_CAP = 10


def refund_retry_delay(attempts):
    return REFUND_RETRY_DELAYS[min(attempts, len(REFUND_RETRY_DELAYS)) - 1]


class Command(BaseCommand):
    help = (
        "Marks departed trips, settles unboarded confirmed bookings "
        "as no-shows, cancels abandoned pending bookings, and retries "
        "failed digital refunds."
    )

    def handle(self, *args, **options):
        now = timezone.now()

        trips = Trip.objects.filter(
            Q(
                status__in=["scheduled", "boarding"],
                departure_at__lte=now,
            )
            | Q(
                status="departed",
                bookings__status="confirmed",
            )
        ).distinct()

        trips_processed = 0
        bookings_settled = 0
        bookings_incident_affected = 0
        bookings_expired = 0
        refunds_retried = 0

        for trip in trips:
            trip_claims = []

            with transaction.atomic():
                trip = (
                    Trip.objects
                    .select_for_update()
                    .get(pk=trip.pk)
                )

                unboarded = (
                    trip.bookings
                    .select_for_update()
                    .filter(status="confirmed")
                )

                # Inside the grace period the trip is marked departed,
                # but nobody is settled as a no-show yet.
                if trip.departure_at > now - GRACE_PERIOD:
                    unboarded = unboarded.none()

                active_incident_exists = trip.incidents.filter(
                    status__in=["reported", "investigating"],
                ).exists()

                for booking in unboarded:
                    # An active trip incident means the passenger was
                    # prevented from boarding by a company/trip event.
                    # Do not classify the passenger as a no-show or
                    # apply an integrity penalty.
                    if active_incident_exists:
                        bookings_incident_affected += 1
                        continue

                    try:
                        _, claim = claim_booking_refund(
                            booking,
                            "passenger",
                        )
                        if claim is not None:
                            trip_claims.append(claim)
                    except ValueError as e:
                        self.stderr.write(
                            f"Refund failed for {booking.booking_number}: {e}"
                        )

                    booking.status = "no_show"
                    booking.save(update_fields=["status"])

                    from django.db.models import F as _F
                    type(booking.user).objects.filter(pk=booking.user_id).update(
                        no_show_count=_F('no_show_count') + 1
                    )
                    bookings_settled += 1

                expired_count = trip.bookings.filter(
                    status="pending"
                ).update(status="cancelled")
                bookings_expired += expired_count

                if trip.status in ("scheduled", "boarding"):
                    trip.status = "departed"
                    trip.save(update_fields=["status"])

                trips_processed += 1

            # Paystack is called only after this trip's row locks are
            # released and its refund reservations are committed.
            run_refund_claims(trip_claims)

        stuck_refunds = Payment.objects.filter(
            method__in=("digital", "wallet"),
            status="confirmed",
            booking__status="no_show",
            refund_status__in=["not_requested", "failed"],
            # A 50% refund must reach Paystack's KES 5 minimum.
            amount__gte=Decimal("10.00"),
        )

        for payment in stuck_refunds:
            try:
                settle_booking_fault(
                    payment.booking,
                    fault_party="passenger",
                )
                refunds_retried += 1
            except ValueError as e:
                self.stderr.write(
                    f"Refund retry failed for "
                    f"{payment.booking.booking_number}: {e}"
                )

        # Refunds Paystack refused when the company cancelled the trip.
        stuck_cancelled_trip_refunds = Payment.objects.filter(
            method__in=("digital", "wallet"),
            status="confirmed",
            booking__status="cancelled",
            booking__trip__status="cancelled",
            refund_status__in=["not_requested", "failed"],
            amount__gte=Decimal("5.00"),
        )

        for payment in stuck_cancelled_trip_refunds:
            try:
                settle_booking_fault(
                    payment.booking,
                    fault_party="company",
                )
                refunds_retried += 1
            except ValueError as e:
                self.stderr.write(
                    f"Refund retry failed for "
                    f"{payment.booking.booking_number}: {e}"
                )

        # Money that arrived for a booking that could not be used (late,
        # resold, cancelled). The refund runs right after the webhook; this
        # is the net for a process that died in between. No trip-status
        # filter: a boarding, departed or cancelled trip still owes it.
        stuck_late_payments = Payment.objects.filter(
            method__in=("digital", "wallet"),
            status="confirmed",
            refund_reason="late_payment",
            refund_status__in=["not_requested", "failed"],
            amount__gte=Decimal("5.00"),
        ).select_related("booking")

        for payment in stuck_late_payments:
            try:
                settle_booking_fault(
                    payment.booking,
                    fault_party="company",
                )
                refunds_retried += 1
            except ValueError as e:
                self.stderr.write(
                    f"Late-payment refund retry failed for "
                    f"{payment.booking.booking_number}: {e}"
                )
                # One alert per payment per day, not one per 10-minute run.
                if cache.add(f"late-refund-alert:{payment.pk}", 1, 24 * 60 * 60):
                    _alert_admin(
                        f"Late payment for booking "
                        f"{payment.booking.booking_number} "
                        f"(KES {payment.amount}) could not be refunded: {e}"
                    )

        # A refund that failed at Paystack for a passenger cancel or a staff
        # company-fault cancel, or one Paystack refused after the seat was
        # resold. The fault party was stored when the refund was claimed.
        fault_parties = {
            "fault_passenger": "passenger",
            "fault_company": "company",
            "seat_lost_passenger": "passenger",
            "seat_lost_company": "company",
        }
        released_before = now - timedelta(minutes=10)
        stuck_fault_refunds = Payment.objects.filter(
            method="digital",
            status="confirmed",
            booking__status__in=["cancelled", "no_show"],
            refund_reason__in=list(fault_parties),
            amount__gte=Decimal("10.00"),
        ).filter(
            Q(refund_next_try_at__isnull=True) | Q(refund_next_try_at__lte=now)
        ).filter(
            Q(refund_status="failed")
            | Q(refund_status="not_requested",
                refund_reason__startswith="seat_lost")
            # A released claim: the cancel may still be restoring the booking.
            | Q(refund_status="not_requested",
                refund_claimed_at__lt=released_before)
        ).select_related("booking")

        for payment in stuck_fault_refunds:
            try:
                settle_booking_fault(
                    payment.booking,
                    fault_party=fault_parties[payment.refund_reason],
                )
                refunds_retried += 1
                if payment.refund_attempts or payment.refund_next_try_at:
                    Payment.objects.filter(pk=payment.pk).update(
                        refund_attempts=0, refund_next_try_at=None)
            except ValueError as e:
                self.stderr.write(
                    f"Refund retry failed for "
                    f"{payment.booking.booking_number}: {e}"
                )
                attempts = payment.refund_attempts + 1
                if attempts >= REFUND_RETRY_CAP:
                    # Out of the sweep for good; one alert, from this transition.
                    Payment.objects.filter(pk=payment.pk).update(
                        refund_attempts=attempts, refund_next_try_at=None,
                        refund_status="review")
                    _alert_admin(
                        f"Refund for booking {payment.booking.booking_number} "
                        f"(KES {payment.amount}) failed {attempts} times and "
                        f"needs review: {e}"
                    )
                    continue
                Payment.objects.filter(pk=payment.pk).update(
                    refund_attempts=attempts,
                    refund_next_try_at=now + refund_retry_delay(attempts))
                if cache.add(f"fault-refund-alert:{payment.pk}", 1, 24 * 60 * 60):
                    _alert_admin(
                        f"Refund for booking {payment.booking.booking_number} "
                        f"(KES {payment.amount}) could not be retried: {e}"
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {trips_processed} departed trip(s), "
                f"settled {bookings_settled} no-show booking(s), "
                f"protected {bookings_incident_affected} "
                f"incident-affected booking(s), "
                f"expired {bookings_expired} abandoned pending booking(s), "
                f"retried {refunds_retried} refund(s)."
            )
        )