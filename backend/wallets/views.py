

# Create your views here.
import re
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from connect import paystack_extra as paystack

from . import config, payouts, topup
from .models import Wallet, WalletPayout, WalletTopUp, WalletTransaction
from .serializers import WalletSerializer, WalletTransactionSerializer
from .throttles import TopUpThrottle, WithdrawThrottle
from rest_framework.decorators import permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_wallet(request):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    wallet, _ = Wallet.objects.get_or_create(user=request.user)

    return Response(WalletSerializer(wallet).data)


_AMOUNT = re.compile(r'^\d{1,7}(\.\d{1,2})?$')


def _error(code, message, http_status, **extra):
    return Response({'code': code, 'error': message, **extra}, status=http_status)


def _passenger_only(user):
    if user.role != 'passenger':
        return _error('passenger_only', 'Wallet top-up is for passenger accounts.',
                      status.HTTP_403_FORBIDDEN)
    return None


def _parse_amount(raw):
    if raw is None or isinstance(raw, bool) or not _AMOUNT.match(str(raw).strip()):
        return None
    amount = Decimal(str(raw).strip())
    return amount if amount > 0 else None


def _paystack_email(user):
    email = user.email or ''
    if '@' in email and '.' in email.split('@')[-1] and ' ' not in email:
        return email
    return f'user_{user.id}@example.com'


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([TopUpThrottle])
def start_topup(request):
    denied = _passenger_only(request.user)
    if denied:
        return denied
    if not config.topup_enabled():
        return _error('topup_disabled', 'Wallet top-up is not available yet.',
                      status.HTTP_503_SERVICE_UNAVAILABLE)

    amount = _parse_amount(request.data.get('amount'))
    if amount is None:
        return _error('invalid_amount', 'Enter an amount in KES, up to 2 decimals.',
                      status.HTTP_400_BAD_REQUEST)
    if amount < config.topup_min():
        return _error('amount_too_small', f'The minimum top-up is KES {config.topup_min()}.',
                      status.HTTP_400_BAD_REQUEST, min=str(config.topup_min()))
    if amount > config.topup_max():
        return _error('amount_too_large', f'The maximum top-up is KES {config.topup_max()}.',
                      status.HTTP_400_BAD_REQUEST, max=str(config.topup_max()))
    wallet = Wallet.objects.filter(user=request.user).first()
    balance = wallet.available_balance if wallet else Decimal('0.00')
    if balance + amount > config.max_balance():
        return _error('balance_cap', f'Your wallet cannot hold more than KES {config.max_balance()}.',
                      status.HTTP_400_BAD_REQUEST,
                      balance=str(balance), max_balance=str(config.max_balance()))

    row = topup.create_topup(request.user, amount)
    try:
        url = paystack.initialize(
            email=_paystack_email(request.user),
            amount=amount,
            reference=row.reference,
            callback_url=f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').rstrip('/')}/passenger/wallet",
            metadata={'purpose': 'wallet_topup', 'user_id': request.user.id},
            channels=config.topup_channels(),
        )
    except paystack.GatewayError as exc:
        # The row stays pending: the request may have reached Paystack, and the sweep expires it.
        return _error('gateway_error', exc.message, status.HTTP_502_BAD_GATEWAY)
    return Response(
        {'reference': row.reference, 'authorization_url': url,
         'amount': str(row.amount), 'status': row.status},
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def topup_status(request, reference):
    denied = _passenger_only(request.user)
    if denied:
        return denied
    row = WalletTopUp.objects.filter(user=request.user, reference=reference).first()
    if row is None:
        return _error('not_found', 'Top-up not found.', status.HTTP_404_NOT_FOUND)
    topup.verify_and_apply(row)
    row.refresh_from_db()
    wallet = Wallet.objects.filter(user=request.user).first()
    return Response({
        'reference': row.reference,
        'status': row.status,
        'amount': str(row.amount),
        'amount_paid': str(row.amount_paid) if row.amount_paid is not None else None,
        'created_at': row.created_at,
        'credited_at': row.credited_at,
        'available_balance': str(wallet.available_balance if wallet else Decimal('0.00')),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_transactions(request):
    denied = _passenger_only(request.user)
    if denied:
        return denied
    rows = (WalletTransaction.objects.filter(wallet__user=request.user)
            .order_by('-created_at', '-id')[:100])
    return Response(WalletTransactionSerializer(rows, many=True).data)


DESTINATION_FIELDS = ('phone', 'phone_number', 'destination', 'msisdn', 'recipient', 'account_number')
PASSWORD_FAILURES_MAX = 5
PASSWORD_LOCK_SECONDS = 15 * 60


def _pw_key(user):
    return f'wallet_withdraw_pw_fail:{user.pk}'


def _payout_data(payout):
    return {
        'payout_id': payout.pk,
        'status': payout.status,
        'amount': str(payout.amount),
        'destination_masked': payouts.masked(payout.destination_phone),
        'created_at': payout.created_at,
    }


@transaction.non_atomic_requests  # the gateway call must never run inside a transaction
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([WithdrawThrottle])
def withdraw(request):
    user = request.user
    denied = _passenger_only(user)
    if denied:
        return denied
    if not config.payouts_enabled():
        return _error('feature_disabled', 'Withdrawals are not available yet.',
                      status.HTTP_503_SERVICE_UNAVAILABLE)
    if any(field in request.data for field in DESTINATION_FIELDS):
        return _error('destination_not_allowed',
                      'Money is only sent to the phone number on your account.',
                      status.HTTP_400_BAD_REQUEST)
    try:
        amount = _parse_amount(request.data.get('amount'))
        if amount is None:
            raise payouts.WithdrawalError('invalid_amount', 'Enter an amount in KES, up to 2 decimals.')
        payouts.validate_amount(amount)
        key = payouts.validate_key(request.data.get('idempotency_key'))
    except payouts.WithdrawalError as exc:
        return _error(exc.code, exc.message, exc.http_status, **exc.extra)

    password = request.data.get('password')
    if not isinstance(password, str) or not password:
        return _error('password_required', 'Enter your password to withdraw.',
                      status.HTTP_400_BAD_REQUEST)
    if cache.get(_pw_key(user), 0) >= PASSWORD_FAILURES_MAX:
        return _error('too_many_attempts', 'Too many wrong passwords. Try again in 15 minutes.',
                      status.HTTP_429_TOO_MANY_REQUESTS)
    if not user.check_password(password):
        # get+set, not incr: DatabaseCache.incr would reset the TTL to the default
        cache.set(_pw_key(user), cache.get(_pw_key(user), 0) + 1, PASSWORD_LOCK_SECONDS)
        return _error('wrong_password', 'That password is not correct.', status.HTTP_403_FORBIDDEN)
    cache.delete(_pw_key(user))

    try:
        payout, created = payouts.withdraw(user, amount, key)
    except payouts.WithdrawalError as exc:
        return _error(exc.code, exc.message, exc.http_status, **exc.extra)
    return Response(_payout_data(payout),
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


PAGE_SIZE = 50


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_withdrawals(request):
    denied = _passenger_only(request.user)
    if denied:
        return denied
    rows = WalletPayout.objects.filter(user=request.user).order_by('-id')
    cursor = request.query_params.get('cursor')
    if cursor not in (None, ''):
        if not str(cursor).isdigit():
            return _error('invalid_cursor', 'Invalid cursor.', status.HTTP_400_BAD_REQUEST)
        rows = rows.filter(id__lt=int(cursor))
    page = list(rows[:PAGE_SIZE + 1])
    more = len(page) > PAGE_SIZE
    page = page[:PAGE_SIZE]
    return Response({
        'results': [_payout_data(p) for p in page],
        'next_cursor': page[-1].pk if more else None,
    })
