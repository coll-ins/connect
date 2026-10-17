from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from bookings.models import UnappliedPayment
from charters.models import CharterRequest


class Command(BaseCommand):
    help = (
        'Cancel a paid (confirmed) bus hire and queue a FULL refund of the charge. '
        'The refund is sent by process_unapplied. Partial refunds are done by hand '
        'in the Paystack dashboard.'
    )

    def add_arguments(self, parser):
        parser.add_argument('reference', help='The hire reference, e.g. CHXXXXXXXX')
        parser.add_argument('--reason', required=True)
        parser.add_argument(
            '--force', action='store_true',
            help='Allow a refund after the departure time has passed.')

    def handle(self, *args, **options):
        with transaction.atomic():
            charter = (
                CharterRequest.objects.select_for_update()
                .filter(reference=options['reference']).first()
            )
            if charter is None:
                raise CommandError('No hire with that reference.')
            if charter.status != 'confirmed':
                raise CommandError(
                    f'Only confirmed (paid) hires can be refunded; this one is {charter.status}.')
            if not charter.provider_reference:
                raise CommandError(
                    'This hire has no payment reference. Refund it manually in Paystack.')
            if charter.quote_price is None or charter.quote_price <= 0:
                raise CommandError('This hire has no valid quote price.')
            if charter.depart_at <= timezone.now() and not options['force']:
                raise CommandError(
                    'The departure time has passed. Re-run with --force if you are sure.')
            if UnappliedPayment.objects.filter(reference=charter.provider_reference).exists():
                raise CommandError(
                    'A refund record already exists for this payment. Check the Paystack dashboard.')

            charter.status = 'cancelled'
            charter.cancelled_at = timezone.now()
            charter.save(update_fields=['status', 'cancelled_at', 'updated_at'])
            UnappliedPayment.objects.create(
                reference=charter.provider_reference,
                kind='charter',
                amount=charter.quote_price,
                currency='KES',
                reason=f"Hire cancelled by admin: {options['reason']}"[:255],
                payload={},
                status='refund_due',
            )
        self.stdout.write(self.style.SUCCESS(
            f'{charter.reference}: cancelled, full refund of KES {charter.quote_price} queued. '
            'It is sent the next time process_unapplied runs.'))
