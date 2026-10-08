"""
Report (default) or record (--apply) a manual payout to a transport company.

Streams in one payout:
  seats     digital, confirmed seat payments that are boarding-eligible, or whose
            refund is processed with part of the fare retained. Per payment:
            retained = amount - processed refund; fee = min(PLATFORM_FEE_PER_SEAT
            x seats, retained), so the company's share is never negative.
            Payments with an unresolved refund are held back and listed.
  charters  bus-hire requests that are completed and were paid through Paystack.
  parcels   parcels that are delivered and were paid through Paystack.
            Charters and parcels: fee = the stream's percentage of the price.

The command only RECORDS the payout you made from Paystack/M-Pesa; it never
moves money. Each charter/parcel can be paid out once (database unique constraint).
"""
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.db.models import Q

from bookings.models import Payment, Payout, PayoutItem
from charters.models import CharterRequest
from companies.models import Company
from deliveries.models import Parcel

CENT = Decimal('0.01')
ZERO = Decimal('0.00')

# kind, setting holding the platform percentage, label
ITEM_STREAMS = (
    ('charter', 'PLATFORM_CHARTER_FEE_PERCENT', 'Charters'),
    ('parcel', 'PLATFORM_PARCEL_FEE_PERCENT', 'Parcels'),
)


def _items(kind, company):
    """Locked, not-yet-paid-out items of one kind as (object, gross) pairs."""
    paid_out = PayoutItem.objects.filter(kind=kind).values('object_id')
    if kind == 'charter':
        qs = CharterRequest.objects.filter(
            company=company, status='completed', quote_price__isnull=False)

        def gross_of(o):
            return o.quote_price
    else:
        qs = Parcel.objects.filter(trip__route__company=company, status='delivered')

        def gross_of(o):
            return o.price

    qs = (
        qs.select_for_update(of=('self',))
        .exclude(provider_reference__isnull=True)
        .exclude(provider_reference='')
        .exclude(id__in=paid_out)
        .order_by('pk')
    )
    return [(o, gross_of(o)) for o in qs]


def _sum(rows, index):
    return sum((r[index] for r in rows), ZERO)


class Command(BaseCommand):
    help = 'Report or record a manual payout to a company.'

    def add_arguments(self, parser):
        parser.add_argument('company_id', type=int)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--reference', default='')
        parser.add_argument('--note', default='')

    def _setting(self, name, upper=None):
        value = getattr(settings, name, None)
        if value is None:
            raise CommandError(f'Set {name} in settings first. Refusing to guess the fee.')
        value = Decimal(str(value))
        if value < 0 or (upper is not None and value > upper):
            raise CommandError(f'{name} is out of range.')
        return value

    def handle(self, *args, **options):
        seat_fee = self._setting('PLATFORM_FEE_PER_SEAT')
        pcts = {
            kind: self._setting(name, upper=Decimal('100'))
            for kind, name, _ in ITEM_STREAMS
        }

        apply = options['apply']
        reference = options['reference'].strip()
        if apply and not reference:
            raise CommandError(
                '--apply needs --reference: the M-Pesa/bank code of the payout you made.'
            )

        try:
            company = Company.objects.get(pk=options['company_id'])
        except Company.DoesNotExist:
            raise CommandError('Company not found.')

        default_refund_state = Payment._meta.get_field('refund_status').get_default()
        clean_states = {'not_requested', 'processed', default_refund_state}

        try:
            with transaction.atomic():
                # ---- seats: rows are (payment, retained, fee) ----
                payments = list(
                    Payment.objects
                    .select_for_update(of=('self',))
                    .select_related('booking')
                    .filter(
                        booking__route__company=company,
                        method='digital',
                        status='confirmed',
                        payout__isnull=True,
                    )
                    .filter(
                        Q(settlement_status='eligible')
                        | Q(settlement_status='not_ready', refund_status='processed')
                    )
                    .order_by('pk')
                )
                seats, held = [], []
                for p in payments:
                    if p.refund_status not in clean_states:
                        held.append(p)
                        continue
                    refunded = (
                        p.refund_amount
                        if p.refund_status == 'processed' and p.refund_amount
                        else ZERO
                    )
                    retained = p.amount - refunded
                    if retained <= 0:
                        continue
                    seats.append((p, retained, min(seat_fee * p.booking.seats, retained)))

                # ---- charters / parcels: rows are (object, gross, fee) ----
                streams = {}
                for kind, _, _ in ITEM_STREAMS:
                    rows = []
                    for obj, gross in _items(kind, company):
                        if gross <= 0:
                            continue
                        fee = min(
                            (gross * pcts[kind] / Decimal('100')).quantize(CENT, ROUND_HALF_UP),
                            gross,
                        )
                        rows.append((obj, gross, fee))
                    streams[kind] = rows

                gross_total = _sum(seats, 1) + sum((_sum(r, 1) for r in streams.values()), ZERO)
                fee_total = _sum(seats, 2) + sum((_sum(r, 2) for r in streams.values()), ZERO)
                net_total = gross_total - fee_total
                item_count = len(seats) + sum(len(r) for r in streams.values())

                self.stdout.write(f'Company: {company}')
                self.stdout.write(
                    f'Seats:    {len(seats)} payment(s); gross {_sum(seats, 1)}, '
                    f'fee {_sum(seats, 2)} (KES {seat_fee} per seat)'
                )
                for kind, _, label in ITEM_STREAMS:
                    rows = streams[kind]
                    self.stdout.write(
                        f'{label}: {len(rows)} item(s); gross {_sum(rows, 1)}, '
                        f'fee {_sum(rows, 2)} ({pcts[kind]}%)'
                    )
                self.stdout.write(f'Platform fee {fee_total}, NET TO PAY {net_total}')
                for p in held:
                    self.stdout.write(
                        f'HELD BACK (refund {p.refund_status}): {p.provider_reference} {p.amount}'
                    )

                if not apply:
                    self.stdout.write('Report only. Nothing recorded. Use --apply --reference CODE.')
                    return
                if item_count == 0:
                    self.stdout.write('Nothing to pay out.')
                    return

                breakdown = {
                    'seats': {
                        'count': len(seats), 'gross': str(_sum(seats, 1)),
                        'fee': str(_sum(seats, 2)), 'fee_per_seat': str(seat_fee),
                    },
                }
                for kind, _, label in ITEM_STREAMS:
                    rows = streams[kind]
                    breakdown[label.lower()] = {
                        'count': len(rows), 'gross': str(_sum(rows, 1)),
                        'fee': str(_sum(rows, 2)), 'percent': str(pcts[kind]),
                    }

                payout = Payout.objects.create(
                    company=company,
                    reference=reference,
                    gross_amount=gross_total,
                    fee_per_seat=seat_fee,
                    fee_amount=fee_total,
                    net_amount=net_total,
                    payments_count=item_count,
                    breakdown=breakdown,
                    note=options['note'][:255],
                )
                if seats:
                    Payment.objects.filter(pk__in=[p.pk for p, _, _ in seats]).update(
                        payout=payout, settlement_status='settled'
                    )
                for kind, _, _ in ITEM_STREAMS:
                    PayoutItem.objects.bulk_create([
                        PayoutItem(
                            payout=payout, kind=kind, object_id=obj.pk,
                            reference=obj.provider_reference,
                            gross_amount=g, fee_amount=f, net_amount=g - f,
                        )
                        for obj, g, f in streams[kind]
                    ])
        except IntegrityError:
            raise CommandError(
                'That payout reference was already used, or an item was paid out by a '
                'concurrent run. Nothing recorded.'
            )

        self.stdout.write(self.style.SUCCESS(
            f'Recorded payout {reference}: {item_count} item(s), net {net_total}.'
        ))
