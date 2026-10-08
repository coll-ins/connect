from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from companies.models import Trip
from bookings.models import Booking, Payment
from bookings.services import (
    claim_booking_refund,
    run_refund_claims,
    settle_booking_fault,
)


# Passengers are only treated as no-shows this long after departure.
GRACE_PERIOD = timedelta(minutes=15)


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

                    booking.user.no_show_count += 1
                    booking.user.save(update_fields=["no_show_count"])
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
            method="digital",
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