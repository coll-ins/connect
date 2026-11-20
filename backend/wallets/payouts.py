"""Wallet withdrawals to the account's own M-Pesa number. Money leaves the system here.

Rules, each one tested:
- the ledger debit (`wd:<id>`) is committed BEFORE the gateway is called;
- the reversal credit (`wdrev:<id>`) happens only after a DEFINITE failure; a
  timeout, 5xx or unreadable answer leaves the payout `requested` and the sweep
  asks the gateway by reference;
- one payout per (user, idempotency key); the gateway is never called inside a
  transaction;
- lock order: Wallet first when creating (a new row cannot be locked by anyone),
  payout row first and then the Wallet (inside services.credit) for every
  status change.
Balances are only ever written through wallets.services.
"""
import logging
import re
import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from users.phone import KENYA_MOBILE, canonical_phone

from . import alerts, config, gateway, services
from .models import Wallet, WalletPayout, WalletPayoutEvent

logger = logging.getLogger(__name__)

REFERENCE_PREFIX = 'wd-'
KEY_PATTERN = re.compile(r'^[A-Za-z0-9_-]{8,64}$')
IN_FLIGHT = ('requested', 'submitted')
COUNTS_TOWARD_LIMIT = ('requested', 'submitted', 'paid', 'review')
WINDOW = timedelta(hours=24)
EVENT_ACTIONS = ('transfer.success', 'transfer.failed', 'transfer.reversed')


class WithdrawalError(Exception):
    def __init__(self, code, message, http_status=400, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.extra = extra


# ------------------------------------------------------------------ validation

def validate_key(key):
    if not isinstance(key, str) or not KEY_PATTERN.match(key):
        raise WithdrawalError('invalid_key', 'idempotency_key must be 8-64 letters, digits, - or _.')
    return key


def validate_amount(amount):
    if not isinstance(amount, (Decimal, int, str)) or isinstance(amount, bool):
        raise WithdrawalError('invalid_amount', 'Enter an amount in KES, up to 2 decimals.')
    try:
        value = Decimal(amount)
    except Exception:
        raise WithdrawalError('invalid_amount', 'Enter an amount in KES, up to 2 decimals.')
    if not value.is_finite() or value <= 0 or value != value.quantize(Decimal('0.01')):
        raise WithdrawalError('invalid_amount', 'Enter an amount in KES, up to 2 decimals.')
    value = value.quantize(Decimal('0.01'))
    if value < config.withdraw_min():
        raise WithdrawalError(
            'amount_too_small', f'The minimum withdrawal is KES {config.withdraw_min()}.',
            min=str(config.withdraw_min()))
    if value > config.withdraw_max():
        raise WithdrawalError(
            'amount_too_large', f'The maximum withdrawal is KES {config.withdraw_max()}.',
            max=str(config.withdraw_max()))
    return value


def masked(phone):
    return phone[:4] + '*' * max(len(phone) - 7, 0) + phone[-3:]


# ------------------------------------------------------------------ request

def rolling_total(user, now=None):
    now = now or timezone.now()
    total = WalletPayout.objects.filter(
        user=user, status__in=COUNTS_TOWARD_LIMIT, created_at__gt=now - WINDOW,
    ).aggregate(s=Sum('amount'))['s']
    return Decimal(total or 0).quantize(Decimal('0.01'))  # SQLite sums are not quantised


def _has_in_flight(user):
    return WalletPayout.objects.filter(user=user, status__in=IN_FLIGHT).exists()


def _transition(payout, to_status, note=''):
    """Caller holds the payout row lock."""
    WalletPayoutEvent.objects.create(
        payout=payout, from_status=payout.status, to_status=to_status, note=note[:255])
    payout.status = to_status
    payout.save(update_fields=['status', 'updated_at'])


def request_withdrawal(user, amount, key):
    """Transaction 1: validate, take the debit, create the payout. Returns (payout, created)."""
    if getattr(user, 'role', None) != 'passenger':
        raise WithdrawalError('passenger_only', 'Withdrawals are for passenger accounts.', 403)
    amount = validate_amount(amount)
    validate_key(key)
    phone = canonical_phone(user.phone_number)
    if not KENYA_MOBILE.match(phone or ''):
        raise WithdrawalError('invalid_phone', 'Your account phone number cannot receive M-Pesa.')

    try:
        with transaction.atomic():
            # Wallet lock first: it serialises every request of this user, so the
            # key lookup, the in-flight check and the rolling limit below cannot race.
            wallet = Wallet.objects.select_for_update().filter(user=user).first()
            if wallet is None:
                raise WithdrawalError('insufficient_funds', 'Your wallet balance is too low.')
            existing = WalletPayout.objects.filter(user=user, idempotency_key=key).first()
            if existing is not None:
                if existing.amount != amount:
                    raise WithdrawalError(
                        'key_reused', 'This request key was already used for a different amount.', 409)
                return existing, False
            if _has_in_flight(user):
                raise WithdrawalError(
                    'payout_in_flight', 'Wait for your current withdrawal to finish.', 409)
            used = rolling_total(user)
            limit = config.withdraw_daily_limit()
            if used + amount > limit:
                raise WithdrawalError(
                    'daily_limit', f'The daily withdrawal limit is KES {limit}.', 400,
                    limit=str(limit), remaining=str(max(limit - used, Decimal('0.00')).quantize(Decimal('0.01'))))
            payout = WalletPayout.objects.create(
                user=user, wallet=wallet, amount=amount, destination_phone=phone,
                idempotency_key=key, reference=f'{REFERENCE_PREFIX}{uuid.uuid4().hex}')
            WalletPayoutEvent.objects.create(payout=payout, from_status='', to_status='requested')
            services.debit(user, amount, 'withdrawal', f'wd:{payout.pk}')
    except services.InsufficientFunds:
        raise WithdrawalError('insufficient_funds', 'Your wallet balance is too low.')
    return payout, True


def withdraw(user, amount, key):
    payout, created = request_withdrawal(user, amount, key)
    if created:
        dispatch(payout.pk)
    payout.refresh_from_db()
    return payout, created


# ------------------------------------------------------------------ gateway step

def dispatch(payout_id):
    """Call the gateway once for a committed payout. Never runs inside a transaction."""
    # Only the caller that moves attempts 0 -> 1 may send; nothing ever resends.
    if not WalletPayout.objects.filter(pk=payout_id, status='requested', attempts=0).update(attempts=1):
        return
    payout = WalletPayout.objects.get(pk=payout_id)
    gw = gateway.get_gateway()
    try:
        recipient = gw.ensure_recipient(payout.destination_phone)
    except Exception as exc:
        # Nothing was sent yet, so reversing is safe.
        _fail(payout_id, f'recipient: {exc}', allowed_from=('requested',))
        return
    try:
        result = gw.send(payout, recipient)
    except Exception:
        logger.exception('Transfer call failed for payout %s', payout_id)
        result = gateway.SendResult(gateway.UNCERTAIN, 'exception')

    if result.outcome == gateway.ACCEPTED:
        with transaction.atomic():
            row = WalletPayout.objects.select_for_update().get(pk=payout_id)
            if row.status == 'requested':  # a webhook may already have finalised it
                row.gateway_transfer_code = result.detail[:100]
                _transition(row, 'submitted')
                row.save(update_fields=['gateway_transfer_code', 'updated_at'])
    elif result.outcome == gateway.REFUSED:
        _fail(payout_id, result.detail, allowed_from=('requested',))
    else:
        logger.warning('Payout %s: transfer result uncertain (%s); the sweep will verify', payout_id, result.detail)


def _fail(payout_id, reason, allowed_from):
    outcome = fail_and_reverse(payout_id, reason, allowed_from=allowed_from)
    if outcome == 'reversed':
        hint = ' Top up the Paystack balance.' if 'balance' in reason.lower() else ''
        alerts.send(f'Payout {payout_id} was refused and reversed: {reason[:120]}.{hint}')
    return outcome


# ------------------------------------------------------------------ status changes

def fail_and_reverse(payout_id, reason, allowed_from=('requested', 'submitted', 'review'), from_paid=False):
    """
    Mark failed and credit the money back, once. Returns 'reversed', 'already_failed' or
    'skipped' (status not allowed: nothing changed).
    """
    with transaction.atomic():
        payout = WalletPayout.objects.select_for_update().get(pk=payout_id)
        if payout.status == 'failed':
            return 'already_failed'
        allowed = set(allowed_from) | ({'paid'} if from_paid else set())
        if payout.status not in allowed:
            return 'skipped'
        services.credit(payout.user, payout.amount, 'withdrawal_reversal', f'wdrev:{payout.pk}')
        payout.failure_reason = reason[:255]
        _transition(payout, 'failed', reason)
        payout.save(update_fields=['failure_reason', 'updated_at'])
        return 'reversed'


def mark_paid(payout_id, allowed_from=('requested', 'submitted', 'review'), note=''):
    """Returns 'paid', 'already_paid', 'conflict' (it was reversed: needs a human) or 'skipped'."""
    with transaction.atomic():
        payout = WalletPayout.objects.select_for_update().get(pk=payout_id)
        if payout.status == 'paid':
            return 'already_paid'
        if payout.status == 'failed':
            return 'conflict'
        if payout.status not in allowed_from:
            return 'skipped'
        _transition(payout, 'paid', note)
        return 'paid'


def send_to_review(payout_id, reason):
    """Returns True when the row was moved to review (the caller alerts)."""
    with transaction.atomic():
        payout = WalletPayout.objects.select_for_update().get(pk=payout_id)
        if payout.status not in IN_FLIGHT:
            return False
        payout.failure_reason = reason[:255]
        _transition(payout, 'review', reason)
        payout.save(update_fields=['failure_reason', 'updated_at'])
        return True


def resolve_review(payout_id, action):
    """Admin decision on a review row: 'paid' or 'reverse'. Raises ValueError if it is not in review."""
    if action == 'paid':
        result = mark_paid(payout_id, allowed_from=('review',), note='admin resolve --paid')
        ok = result == 'paid'
    else:
        result = fail_and_reverse(payout_id, 'admin resolve --reverse', allowed_from=('review',))
        ok = result == 'reversed'
    if not ok:
        raise ValueError(f'payout {payout_id} is not in review ({result})')
    logger.warning('Payout %s resolved by admin: %s', payout_id, action)


# ------------------------------------------------------------------ webhook

def _matches(payout, data):
    amount, currency = data.get('amount'), data.get('currency')
    if amount is not None:
        try:
            if int(amount) != int(payout.amount * 100):
                return False
        except (TypeError, ValueError):
            return False
    return currency in (None, 'KES')


def apply_transfer_event(name, data):
    """True when the event is about one of our payouts (reference wd-...). Bad data alerts and is ignored."""
    data = data if isinstance(data, dict) else {}
    reference = data.get('reference')
    if not isinstance(reference, str) or not reference.startswith(REFERENCE_PREFIX):
        return False
    payout = WalletPayout.objects.filter(reference=reference).first()
    if payout is None:
        alerts.send(f'{name} for unknown withdrawal reference {reference}. Check Paystack.')
        return True
    if not _matches(payout, data):
        alerts.send(f'{name} for payout {payout.pk} has a different amount or currency. '
                    'Nothing changed; check Paystack.')
        return True

    if name == 'transfer.success':
        if mark_paid(payout.pk, note='webhook transfer.success') == 'conflict':
            alerts.send(f'Payout {payout.pk} was reversed to the wallet but Paystack says it was PAID. '
                        'The user may have the money twice. Check Paystack.')
    elif name == 'transfer.failed':
        if fail_and_reverse(payout.pk, 'webhook transfer.failed') == 'skipped':
            alerts.send(f'transfer.failed for payout {payout.pk} which is already paid. Nothing changed; check Paystack.')
    else:
        if fail_and_reverse(payout.pk, 'webhook transfer.reversed', from_paid=True) == 'skipped':
            alerts.send(f'transfer.reversed for payout {payout.pk} in an unexpected state. Nothing changed.')
    return True
