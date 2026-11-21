"""Paystack M-Pesa top-up: one TopUp row per attempt, credited exactly once.

Credit paths (webhook, verify-on-read, sweep) all go through apply_topup_charge
and are never gated by WALLET_TOPUP_ENABLED; that flag only hides the init.
"""
import logging
import uuid

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from connect import paystack_extra as paystack

from . import alerts, services
from .models import WalletTopUp

logger = logging.getLogger(__name__)

TOPUP_PREFIX = 'TOPUP-'
VERIFY_COOLDOWN_SECONDS = 5


def create_topup(user, amount):
    """Create the pending row and commit it before any gateway call."""
    with transaction.atomic():
        row = WalletTopUp.objects.create(
            user=user, amount=amount, reference=f'{TOPUP_PREFIX}new-{uuid.uuid4().hex}')
        row.reference = paystack.new_reference('TOPUP', row.pk)
        row.save(update_fields=['reference'])
    return row


def _metadata_user_id(data):
    metadata = data.get('metadata')
    return str(metadata.get('user_id')) if isinstance(metadata, dict) else None


def apply_topup_charge(reference, data):
    """
    Credit the money Paystack says it received, once. Returns one of
    'credited', 'already_credited', 'pending', 'review', 'unknown'.
    """
    problem = None
    with transaction.atomic():
        # TopUp row first, then the Wallet (inside services.credit).
        row = WalletTopUp.objects.select_for_update().filter(reference=reference).first()
        if row is None:
            result, problem = 'unknown', f'Top-up {reference} was paid but no such top-up exists.'
        elif row.status == 'credited':
            result = 'already_credited'
        elif row.status == 'review':
            result = 'review'
        elif data.get('status') != 'success':
            result = 'pending'
        else:
            result, problem = _credit(row, data)
    if problem:
        alerts.send(problem)
    return result


def _credit(row, data):
    try:
        paid = paystack.to_kes(data.get('amount'))
    except paystack.GatewayError:
        paid = None
    reason = None
    if data.get('currency') != 'KES':
        reason = 'currency is not KES'
    elif paid is None or paid <= 0:
        reason = 'amount is unreadable or not positive'
    elif _metadata_user_id(data) != str(row.user_id):
        reason = 'charge belongs to a different user'
    if reason:
        row.status = 'review'
        row.amount_paid = paid if paid is not None and paid > 0 else None
        row.save(update_fields=['status', 'amount_paid'])
        return 'review', f'Top-up {row.reference} NOT credited: {reason}. Check Paystack.'

    services.credit(row.user, paid, 'deposit', f'topup:{row.reference}')
    row.status = 'credited'
    row.amount_paid = paid
    row.credited_at = timezone.now()
    row.save(update_fields=['status', 'amount_paid', 'credited_at'])
    problem = None
    if paid != row.amount:
        problem = (f'Top-up {row.reference}: requested KES {row.amount} but Paystack '
                   f'received KES {paid}. Credited KES {paid}.')
    return 'credited', problem


def verify_and_apply(row, cooldown=True):
    """Ask Paystack about a pending/expired top-up and apply the answer. Call outside any transaction."""
    if row.status not in ('pending', 'expired'):
        return row.status
    if cooldown and not cache.add(f'wallet_topup_verify:{row.reference}', 1, VERIFY_COOLDOWN_SECONDS):
        return row.status
    try:
        data = paystack.verify(row.reference)
    except paystack.GatewayError:
        logger.warning('Top-up verify failed for %s', row.reference)
        return row.status
    if data.get('reference') != row.reference:
        return row.status
    return apply_topup_charge(row.reference, data)
