from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from bookings.services import run_refund_claims, settle_unboarded_no_shows
from companies.models import Trip


ACTIVE_INCIDENT_STATUSES = ('reported', 'investigating')


class Command(BaseCommand):
    help = (
        'Close old departed trips that have no confirmed bookings. Trips '
        'with confirmed bookings are left open and listed for manual '
        'review: a trip nobody ended may also have had nobody marked '
        'as boarded, so no-show penalties are never applied automatically.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--older-than-hours',
            type=int,
            default=getattr(settings, 'TRIP_AUTO_CLOSE_AFTER_HOURS', 12),
            help='Close departed trips at least this old (default: 12 hours).',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Close at most this many trips in one run.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='List eligible trips without changing trips, bookings or refunds.',
        )

    def handle(self, *args, **options):
        hours = options['older_than_hours']
        limit = options['limit']
        if hours < 1:
            raise CommandError('--older-than-hours must be at least 1.')
        if limit is not None and limit < 1:
            raise CommandError('--limit must be at least 1.')

        cutoff = timezone.now() - timedelta(hours=hours)
        candidates = (
            Trip.objects
            .filter(status='departed', departure_at__lte=cutoff)
            .exclude(incidents__status__in=ACTIVE_INCIDENT_STATUSES)
            .distinct()
            .order_by('pk')
        )

        if options['dry_run']:
            all_ids = list(candidates.values_list('pk', flat=True))
            review_ids = set(
                candidates.filter(bookings__status='confirmed')
                .values_list('pk', flat=True)
            )
            closable = [i for i in all_ids if i not in review_ids]
            self.stdout.write(
                f'close_stale_trips: {len(closable)} trip(s) would close, '
                f'{len(review_ids)} need manual review (confirmed bookings), '
                f'older than {hours} hour(s); no changes made.'
            )
            if closable:
                self.stdout.write(
                    'Would close: ' + ', '.join(map(str, closable[:50]))
                )
            if review_ids:
                self.stdout.write(
                    'Needs review: ' + ', '.join(map(str, sorted(review_ids)))
                )
            return

        closed = cancelled = 0
        review = []
        for trip_id in list(candidates.values_list('pk', flat=True)):
            if limit is not None and closed >= limit:
                break

            claims = []
            with transaction.atomic():
                try:
                    trip = Trip.objects.select_for_update().get(pk=trip_id)
                except Trip.DoesNotExist:
                    continue

                if (
                    trip.status != 'departed'
                    or trip.departure_at > cutoff
                    or trip.incidents.filter(
                        status__in=ACTIVE_INCIDENT_STATUSES,
                    ).exists()
                ):
                    continue

                if trip.bookings.filter(status='confirmed').exists():
                    review.append(trip.pk)
                    continue

                pending = trip.bookings.filter(status='pending').count()
                settle_unboarded_no_shows(trip, claims=claims)
                trip.status = 'completed'
                trip.save(update_fields=['status'])
                closed += 1
                cancelled += pending

            run_refund_claims(claims)

        self.stdout.write(
            self.style.SUCCESS(
                f'close_stale_trips: closed {closed} trip(s), '
                f'cancelled {cancelled} pending booking(s), '
                f'left {len(review)} trip(s) for manual review.'
            )
        )
        if review:
            self.stdout.write(
                self.style.WARNING(
                    'Needs review (confirmed bookings): '
                    + ', '.join(map(str, review))
                )
            )
