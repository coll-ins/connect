import datetime as dt

from django.db.models import DecimalField, F, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

import logging

from django.core.cache import cache

from . import alerts, gateway, payouts, topup
from .models import Wallet, WalletPayout, WalletTopUp

VERIFY_AFTER = dt.timedelta(minutes=5)
EXPIRE_AFTER = dt.timedelta(hours=24)
PAYOUT_CHECK_AFTER = dt.timedelta(minutes=2)
PAYOUT_STUCK_AFTER = dt.timedelta(minutes=30)
PAYOUT_REVIEW_AFTER = dt.timedelta(hours=24)
STUCK_ALERT_EVERY = 60 * 60

logger = logging.getLogger(__name__)


def sweep_topups(now=None):
    """Verify lost-webhook top-ups, then expire the ones nobody paid. Returns (checked, expired)."""
    now = now or timezone.now()
    window = WalletTopUp.objects.filter(
        status='pending', created_at__lte=now - VERIFY_AFTER, created_at__gt=now - EXPIRE_AFTER)
    checked = 0
    for row in window:
        topup.verify_and_apply(row, cooldown=False)
        checked += 1
    expired = WalletTopUp.objects.filter(
        status='pending', created_at__lte=now - EXPIRE_AFTER).update(status='expired')
    return checked, expired


def ledger_drift():
    """Wallets whose balance differs from the sum of their ledger. Read-only."""
    zero = Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
    return list(
        Wallet.objects
        .annotate(ledger_total=Coalesce(Sum('transactions__amount'), zero))
        .exclude(available_balance__exact=F('ledger_total'))
        .values_list('user_id', 'available_balance', 'ledger_total')
    )


def sweep_payouts(now=None):
    """
    Resolve payouts that are neither paid nor failed by asking the gateway by reference.
    Never resends and never reverses on anything but a definite failure. Not gated by
    WALLET_PAYOUTS_ENABLED: money already in flight must always be finalised.
    """
    now = now or timezone.now()
    result = {'checked': 0, 'paid': 0, 'reversed': 0, 'review': 0, 'pending': 0, 'errors': 0}
    rows = WalletPayout.objects.filter(
        status__in=payouts.IN_FLIGHT, created_at__lte=now - PAYOUT_CHECK_AFTER).order_by('id')
    gw = gateway.get_gateway()
    for row in list(rows):
        result['checked'] += 1
        try:
            status = gw.status(row.reference)
        except Exception:
            logger.exception('status() failed for payout %s', row.pk)
            status = 'error'
        if status not in gateway.STATUS_VALUES:
            status = 'error'
        age = now - row.created_at

        if status == 'success':
            if payouts.mark_paid(row.pk, allowed_from=payouts.IN_FLIGHT, note='sweep status=success') == 'conflict':
                alerts.send(f'Payout {row.pk} was reversed to the wallet but Paystack says it was PAID. '
                            'Check Paystack.')
            result['paid'] += 1
        elif status in ('failed', 'reversed'):
            if payouts.fail_and_reverse(
                    row.pk, f'sweep status={status}', allowed_from=payouts.IN_FLIGHT) == 'reversed':
                result['reversed'] += 1
        elif status in ('otp', 'review', 'not_found'):
            _review(row, f'gateway status {status}', result)
        elif age >= PAYOUT_REVIEW_AFTER:
            _review(row, f'still {status} after 24 hours', result)
        else:
            result['pending' if status == 'pending' else 'errors'] += 1
            if age >= PAYOUT_STUCK_AFTER and cache.add(f'wallet_payout_stuck:{row.pk}', 1, STUCK_ALERT_EVERY):
                alerts.send(f'Payout {row.pk} (KES {row.amount}) is stuck in {row.status} for over '
                            f'{int(PAYOUT_STUCK_AFTER.total_seconds() // 60)} minutes.')
    return result


def _review(row, reason, result):
    if payouts.send_to_review(row.pk, reason):
        result['review'] += 1
        alerts.send(f'Payout {row.pk} (KES {row.amount}, user {row.user_id}) needs review: {reason}. '
                    'Check Paystack, then run resolve_payout.')


def review_rows():
    return list(WalletPayout.objects.filter(status='review').order_by('id'))
