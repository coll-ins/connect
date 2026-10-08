"""
Work through charges (parcels / bus hire) that could not be applied.

1. Retry transient failures (up to 5 attempts, then a human).
2. Send automatic refunds for business rejections (refund_due).
3. Check refunds stuck in 'refunding' against Paystack. It never resends:
   if Paystack has no refund after the minimum age, a human takes over.
Run from cron every 5 minutes.
"""
from datetime import timedelta

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.utils import timezone

from bookings.models import UnappliedPayment
from connect import paystack_extra as px

MAX_ATTEMPTS = 5


class Command(BaseCommand):
    help = 'Retry, refund and reconcile charges that could not be applied.'

    def add_arguments(self, parser):
        parser.add_argument('--min-age-minutes', type=int, default=30)

    def handle(self, *args, **options):
        applied = escalated = refunded = reconciled = 0

        # 1. transient failures
        for row in UnappliedPayment.objects.filter(status='retry').order_by('pk'):
            attempts = row.attempts + 1
            try:
                px.apply_charge(row.reference, row.payload)
            except Exception as exc:
                action, reason, _ = px.classify_failure(exc, row.payload)
                if action == 'refund':
                    new_status, tail = 'refund_due', 'Automatic refund queued; no action needed.'
                elif action == 'review' or attempts >= MAX_ATTEMPTS:
                    new_status, tail = 'review', 'Needs a human: check Paystack and refund manually if appropriate.'
                else:
                    new_status, tail = 'retry', ''
                changed = UnappliedPayment.objects.filter(pk=row.pk, status='retry').update(
                    status=new_status, attempts=attempts,
                    reason=reason[:255], updated_at=timezone.now(),
                )
                if changed and new_status != 'retry':
                    px._alert(f'Payment {row.reference} could not be applied ({reason[:80]}). {tail}')
                    escalated += 1
            else:
                if UnappliedPayment.objects.filter(pk=row.pk, status='retry').update(
                        status='applied', attempts=attempts, updated_at=timezone.now()):
                    applied += 1

        # 2. automatic refunds (the claim is a conditional UPDATE: one winner)
        for row in UnappliedPayment.objects.filter(status='refund_due').order_by('pk'):
            if px.claim_refund(row):
                row.refresh_from_db()
                if px.send_refund(row):
                    refunded += 1

        # 3. refunds stuck in 'refunding'
        cutoff = timezone.now() - timedelta(minutes=options['min_age_minutes'])
        for row in UnappliedPayment.objects.filter(status='refunding', updated_at__lt=cutoff):
            result = px.reconcile_refund(row)
            if result == 'refunded':
                reconciled += 1
            elif result == 'none':
                px._finish(row, status='review', reason='refund never reached Paystack')
                px._alert(
                    f'Charge {row.reference} (KES {row.amount}): the automatic refund '
                    f'never reached Paystack. Refund manually.'
                )
            elif result == 'odd':
                key = f'unapplied-alert:{row.pk}:{int(row.updated_at.timestamp())}'
                if cache.add(key, 1, 24 * 60 * 60):
                    px._alert(
                        f'Charge {row.reference}: Paystack shows an unexpected refund '
                        f'state. Check the dashboard.'
                    )

        self.stdout.write(
            f'process_unapplied: applied {applied}, escalated {escalated}, '
            f'refunded {refunded}, reconciled {reconciled}'
        )
        for row in UnappliedPayment.objects.filter(status='review').order_by('pk'):
            self.stdout.write(f'NEEDS A HUMAN: {row.reference} KES {row.amount}: {row.reason}')
