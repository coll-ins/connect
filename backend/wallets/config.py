"""Wallet limits and flags. Read with defaults so the app works before settings.py defines them."""
from decimal import Decimal

from django.conf import settings


def _get(name, default):
    return getattr(settings, name, default)


def topup_enabled():
    return bool(_get('WALLET_TOPUP_ENABLED', False))


def topup_channels():
    return list(_get('WALLET_TOPUP_CHANNELS', ['mobile_money']))


def topup_min():
    return Decimal(str(_get('WALLET_TOPUP_MIN_KES', 50)))


def topup_max():
    return Decimal(str(_get('WALLET_TOPUP_MAX_KES', 20000)))


def max_balance():
    return Decimal(str(_get('WALLET_MAX_BALANCE_KES', 50000)))


def payouts_enabled():
    return bool(_get('WALLET_PAYOUTS_ENABLED', False))


def withdraw_min():
    return Decimal(str(_get('WALLET_WITHDRAW_MIN_KES', 50)))


def withdraw_max():
    return Decimal(str(_get('WALLET_WITHDRAW_MAX_KES', 20000)))


def withdraw_daily_limit():
    return Decimal(str(_get('WALLET_WITHDRAW_DAILY_LIMIT_KES', 30000)))
