"""
Reconcile claimed/pending refunds against what Paystack reports.

It never creates a refund on its own. It records a refund Paystack confirms,
flags anything odd for a human (one SMS per payment, not one per run), and
re-sends a refund that provably never reached Paystack, but only with --resend.
"""
from datetime import timedelta
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from bookings.models import Payment, UnappliedPayment
from connect.paystack_extra import refunds_of_transaction, route_refund
from bookings.services import (
    RefundClaim,
    RefundRejected,
    _alert_admin,
    execute_booking_refund,
    record_refund_result,
    release_refund_claim,
)

LIST_URL = 'https://api.paystack.co/refund'
CONFIRMED = {'pending', 'processing', 'processed'}
ALERT_TTL = 24 * 60 * 60


class Command(BaseCommand):
    help = 'Reconcile claimed/pending refunds against Paystack.'

    def add_arguments(self, parser):
        parser.add_argument('--min-age-minutes', type=int, default=30)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument(
            '--resend',
            action='store_true',
            help='Resend refunds that never reached Paystack. Check the '
                 'Paystack dashboard first: a resend cannot be undone.',
        )

    def _fetch(self, reference):
        """Return Paystack's refunds for a transaction, or None if unknown."""
        try:
            response = requests.get(
                LIST_URL,
                params={'reference': reference},
                headers={'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}'},
                timeout=30,
            )
            body = response.json()
        except (requests.RequestException, ValueError):
            return None
        if response.status_code != 200 or not body.get('status'):
            return None
        return refunds_of_transaction(body.get('data') or [], reference)

    def _flag(self, payment, message, dry):
        self.flagged += 1
        self.stderr.write(f'{payment.provider_reference}: {message}')
        if dry:
            return
        stamp = int(payment.refund_claimed_at.timestamp()) if payment.refund_claimed_at else 0
        if cache.add(f'reconcile-alert:{payment.pk}:{stamp}', 1, ALERT_TTL):
            _alert_admin(f'Refund for payment {payment.provider_reference}: {message}')

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=options['min_age_minutes'])
        dry, resend = options['dry_run'], options['resend']
        self.flagged = recorded = resent = skipped = 0

        stuck = (
            Payment.objects.select_related('booking')
            .filter(method='digital', refund_status__in=['processing', 'pending'])
            .filter(Q(refund_claimed_at__lt=cutoff) | Q(refund_claimed_at__isnull=True))
            .exclude(provider_reference__isnull=True)
            .exclude(provider_reference='')
        )

        for payment in stuck:
            ref = payment.provider_reference
            refunds = self._fetch(ref)

            if refunds is None:
                skipped += 1
                self.stderr.write(f'{ref}: could not ask Paystack; left as is')
                continue

            if payment.refund_amount is None:
                self._flag(payment, 'refund is open with no amount recorded; check manually.', dry)
                continue

            claim = RefundClaim(
                payment.pk, payment.booking_id, payment.booking.booking_number,
                ref, payment.refund_amount,
            )

            # An overpayment's refund on the same charge is a sibling record,
            # not an extra: pick ours by its stored id, then by amount.
            expected = int(payment.refund_amount * Decimal('100'))
            siblings = UnappliedPayment.objects.filter(
                reference=ref, status__in=['refunding', 'refunded'])
            verdict, item = route_refund(
                refunds,
                payment.refund_reference,
                expected,
                [r.refund_reference for r in siblings if r.refund_reference],
                [int(r.amount * 100) for r in siblings
                 if not r.refund_reference and r.amount],
            ) if refunds else ('none', None)

            if verdict == 'ambiguous':
                self._flag(payment, f'{len(refunds)} refunds exist at Paystack and none can be told apart from the others; left for a human.', dry)
                continue

            if verdict == 'none':
                never_sent = (
                    payment.refund_status == 'processing'
                    and not payment.refund_reference
                )
                if not never_sent:
                    self._flag(payment, 'Paystack acknowledged this refund earlier but lists none now; check the dashboard.', dry)
                elif resend and not dry:
                    try:
                        execute_booking_refund(claim)
                    except RefundRejected as exc:
                        release_refund_claim(claim)
                        self._flag(payment, f'resend rejected by Paystack ({exc}); claim released, needs a human.', dry)
                    except ValueError as exc:
                        self._flag(payment, f'resend outcome unknown ({exc}); check Paystack.', dry)
                    else:
                        resent += 1
                        self.stdout.write(f'{ref}: never reached Paystack; resent')
                else:
                    self._flag(payment, 'NO refund exists at Paystack. Check the dashboard, then rerun with --resend.', dry)
                continue

            amount = item.get('amount')
            problem = None

            if item.get('status') not in CONFIRMED:
                problem = f'Paystack refund status is {item.get("status")!r}'
            elif amount is not None and int(amount) != expected:
                problem = f'amount mismatch (Paystack {amount}, expected {expected})'

            if problem:
                self._flag(payment, f'{problem}; left for a human.', dry)
                continue

            if not dry:
                record_refund_result(claim, item['status'], item.get('id'))
            recorded += 1
            self.stdout.write(f'{ref}: recorded as {item["status"]}')

        self.stdout.write(
            f'reconcile_refunds: recorded {recorded}, resent {resent}, '
            f'flagged {self.flagged}, skipped {skipped}' + (' (dry run)' if dry else '')
        )
