"""The only writer of wallet balances and ledger rows.

Callers must already hold any Trip/Booking/Payment/Hold/request-row locks they
need: the Wallet lock is taken here and is always last. A ledger row with a
booking takes a share lock on that Booking (foreign key check), so a caller
that credits or debits for a booking must lock the Booking first.
"""
from decimal import Decimal, InvalidOperation

from django.db import connection

from .models import Wallet, WalletTransaction


class InsufficientFunds(Exception):
    pass


def _clean_amount(amount):
    if not isinstance(amount, (Decimal, int, str)) or isinstance(amount, bool):
        raise ValueError('amount must be a Decimal, int or str')
    try:
        value = Decimal(amount)
    except InvalidOperation:
        raise ValueError('amount is not a number')
    if not value.is_finite() or value <= 0 or value != value.quantize(Decimal('0.01')):
        raise ValueError('amount must be positive with at most 2 decimal places')
    return value.quantize(Decimal('0.01'))


def _locked_wallet(user):
    Wallet.objects.get_or_create(user=user)
    return Wallet.objects.select_for_update().get(user=user)


def _move(user, amount, type, reference, booking, sign):
    assert connection.in_atomic_block, 'wallet movements must run inside transaction.atomic()'
    amount = _clean_amount(amount)
    if type not in dict(WalletTransaction.TYPE_CHOICES):
        raise ValueError(f'unknown ledger type {type!r}')
    if not reference:
        raise ValueError('reference is required')

    wallet = _locked_wallet(user)
    # Checked after the Wallet lock: a racing caller with the same reference
    # waits here and then sees the first one's row.
    existing = WalletTransaction.objects.filter(reference=reference).first()
    if existing is not None:
        return existing

    delta = amount * sign
    new_balance = wallet.available_balance + delta
    if new_balance < 0:
        raise InsufficientFunds(f'balance {wallet.available_balance} is less than {amount}')
    row = WalletTransaction.objects.create(
        wallet=wallet, booking=booking, type=type, amount=delta,
        balance_after=new_balance, reference=reference,
    )
    wallet.available_balance = new_balance
    wallet.save(update_fields=['available_balance'])
    return row


def credit(user, amount, type, reference, booking=None):
    return _move(user, amount, type, reference, booking, 1)


def debit(user, amount, type, reference, booking=None):
    return _move(user, amount, type, reference, booking, -1)
