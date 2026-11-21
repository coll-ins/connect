from connect.frontend import frontend_url
from django.core.exceptions import ValidationError as DjangoValidationError
from connect.validation import free_text, kenyan_mobile
from django.db.models import Q, Sum
import hmac
import logging
import hashlib
import json
import requests
import uuid

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from rest_framework import status
from rest_framework.decorators import (
    api_view,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle

from companies.models import Trip, PickupStage
from .models import Incident, IncidentResolution
from users.permissions import can_manage_company, can_access_company
from notifications import push
from notifications.sms import send_admin_alert_sms
from drivers.models import Driver

from .models import Booking, BookingHold, Payment, BoardingEvent
from .seats import (
    SeatError, assign_seats, ensure_numbers, move_seats, purge_dead_rows, seat_map,
)
from .services import (
    settle_booking_fault,
    cancel_dead_pending_bookings,
    cash_due_on_board,
    before_change_cutoff,
    cash_still_payable,
    trip_has_departed,
    release_booking_hold,
    NotEnoughSeats,
    BookingMoved,
    WalletPayRefused,
    pay_booking_from_wallet,
    booking_closes_at,
    confirm_booking_payment,
    hold_deadline,
    hold_expired_and_seat_gone,
    lock_trip_then_booking,
    record_unmatched_charge,
    active_seat_q,
    reserve_seats,
    seats_taken,
)
from .serializers import (
    BookingCreateSerializer,
    AssignDriverSerializer,
    PassengerLocationSerializer,
    IncidentSerializer,
)
from users.identity import drivers_for_user, is_driver_account_for
from users.route_scope import operator_route_ids
from connect.ids import parse_id


# ============================================================
# BOARDING VERIFICATION THROTTLE
# ============================================================

class BoardingVerifyThrottle(SimpleRateThrottle):
    """
    Limits boarding verification attempts.

    Uses a custom throttle class instead of ScopedRateThrottle
    because DRF's @api_view decorator does not reliably forward
    a throttle_scope attribute to the generated view.
    """

    scope = 'boarding_verify'

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)

        return self.cache_format % {
            'scope': self.scope,
            'ident': ident,
        }


class BusRerouteThrottle(SimpleRateThrottle):
    """Limits calls to the outside road service from one user's map."""

    scope = 'bus_reroute'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': request.user.pk,
        }


BUS_REROUTE_CACHE_SECONDS = 60


# ============================================================
# PAYSTACK PAYMENT INITIALIZATION
# ============================================================

def _release_dead_digital_attempt(booking_id, user):
    """
    Before a new payment attempt is refused because a digital one is
    "in progress", ask Paystack about it. A checkout the passenger closed or a
    payment that failed is marked failed, so they can retry or switch to cash.
    Anything else (paid, still running, Paystack unreachable) is left alone.
    Runs outside any row lock so the HTTP call never holds the booking.
    """
    payment = (
        Payment.objects
        .filter(booking_id=booking_id, booking__user=user,
                status='pending', method='digital')
        .exclude(provider_reference__isnull=True)
        .exclude(provider_reference='')
        .first()
    )
    if payment is None:
        return
    reference = payment.provider_reference
    try:
        response = requests.get(
            f'https://api.paystack.co/transaction/verify/{reference}',
            headers={'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}'},
            timeout=15,
        )
        result = response.json()
    except (requests.RequestException, ValueError):
        return
    if response.status_code != 200 or not isinstance(result, dict) or not result.get('status'):
        return
    if (result.get('data') or {}).get('status') in ('failed', 'abandoned', 'reversed'):
        # Conditional update: a webhook that confirmed it meanwhile wins.
        Payment.objects.filter(
            pk=payment.pk, status='pending', provider_reference=reference,
        ).update(status='failed')


def _tampered_amount(request, expected):
    """
    The amount is always computed on the server. A client may send `amount`
    or `total_amount` only if it repeats that figure; anything else is refused
    before any payment row or gateway call exists.
    """
    from decimal import InvalidOperation

    for field in ('amount', 'total_amount'):
        sent = request.data.get(field)
        if sent is None or sent == '':
            continue
        try:
            same = Decimal(str(sent)) == expected
        except (InvalidOperation, ValueError):
            same = False
        if not same:
            return Response(
                {
                    'error': 'The amount does not match this booking.',
                    'code': 'amount_mismatch',
                    'expected': str(expected),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
    return None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def initialize_paystack_payment(request, booking_id):
    """Initialize one Paystack checkout attempt for a booking."""
    _release_dead_digital_attempt(booking_id, request.user)

    try:
        with transaction.atomic():
            booking = (
                Booking.objects
                .select_for_update()
                .get(
                    id=booking_id,
                    user=request.user,
                )
            )

            if booking.status in ('cancelled', 'no_show'):
                return Response(
                    {'error': 'Cancelled bookings cannot be paid for'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if booking.status == 'completed':
                return Response(
                    {'error': 'This booking is already completed'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            tampered = _tampered_amount(request, booking.total_amount)
            if tampered is not None:
                return tampered

            if trip_has_departed(booking.trip):
                return Response(
                    {
                        'error': (
                            'This trip has already departed. '
                            'Payment can no longer be made.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            existing_payment = (
                Payment.objects
                .select_for_update()
                .filter(booking=booking)
                .first()
            )

            if (
                existing_payment
                and existing_payment.status == 'confirmed'
            ):
                return Response(
                    {'error': 'This booking has already been paid for'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Never overwrite a live digital payment reference.
            # A later webhook must always map to the same payment row.
            if (
                existing_payment
                and existing_payment.status == 'pending'
                and existing_payment.method == 'digital'
                and existing_payment.provider_reference
            ):
                return Response(
                    {
                        'error': (
                            'A digital payment is already in progress '
                            'for this booking.'
                        ),
                        'reference': existing_payment.provider_reference,
                    },
                    status=status.HTTP_409_CONFLICT
                )

            reference = (
                f'CONNECT-{booking.id}-{uuid.uuid4().hex}'
            )

            if existing_payment:
                payment = existing_payment
                payment.amount = booking.total_amount
                payment.method = 'digital'
                payment.status = 'pending'
                payment.settlement_status = 'not_ready'
                payment.provider_reference = reference
                payment.idempotency_key = reference
                payment.confirmed_at = None
                payment.refunded_at = None
                payment.refund_reference = None
                payment.refund_status = 'not_requested'
                payment.refund_reason = ''
                payment.paid_amount = None
                payment.save(
                    update_fields=[
                        'amount',
                        'method',
                        'status',
                        'settlement_status',
                        'provider_reference',
                        'idempotency_key',
                        'confirmed_at',
                        'refunded_at',
                        'refund_reference',
                        'refund_status',
                        'refund_reason',
                        'paid_amount',
                    ]
                )
            else:
                payment = Payment.objects.create(
                    booking=booking,
                    amount=booking.total_amount,
                    method='digital',
                    status='pending',
                    settlement_status='not_ready',
                    provider_reference=reference,
                    idempotency_key=reference,
                )

    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    amount_in_cents = int(
        booking.total_amount * Decimal('100')
    )

    headers = {
        'Authorization': f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        'Content-Type': 'application/json',
    }

    payload = {
        'email': (
            request.user.email
            if request.user.email and '@' in request.user.email
            and '.' in request.user.email.split('@')[-1]
            and ' ' not in request.user.email
            else f"user_{request.user.id}@example.com"
        ),
        'amount': amount_in_cents,
        'currency': 'KES',
        'reference': reference,
        'callback_url': frontend_url(request, f'/passenger/payment/{booking.id}'),
        'metadata': {
            'booking_id': booking.id,
            'user_id': request.user.id,
        }
    }

    try:
        response = requests.post(
            'https://api.paystack.co/transaction/initialize',
            json=payload,
            headers=headers,
            timeout=30
        )
    except requests.RequestException:
        return Response(
            {
                'error': (
                    'Unable to confirm the payment gateway request. '
                    'Check the payment status before retrying.'
                ),
                'reference': reference,
            },
            status=status.HTTP_502_BAD_GATEWAY
        )

    if response.status_code != 200:
        # Paystack answered and refused, so no checkout exists: release the
        # attempt so the passenger can retry. A 5xx stays "in progress".
        if response.status_code < 500 and response.status_code != 429:
            Payment.objects.filter(pk=payment.pk, status='pending').update(
                status='failed')
        return Response(
            {
                'error': 'Failed to initialize payment gateway',
                'reference': reference,
            },
            status=status.HTTP_502_BAD_GATEWAY
        )

    try:
        res_data = response.json()
    except ValueError:
        return Response(
            {
                'error': 'Invalid response from payment gateway',
                'reference': reference,
            },
            status=status.HTTP_502_BAD_GATEWAY
        )

    if not res_data.get('status'):
        Payment.objects.filter(pk=payment.pk, status='pending').update(
            status='failed')
        return Response(
            {
                'error': res_data.get(
                    'message',
                    'Payment initialization error'
                ),
                'reference': reference,
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    data = res_data.get('data') or {}
    returned_reference = data.get('reference')

    if not data.get('authorization_url') or not returned_reference:
        return Response(
            {
                'error': 'Payment gateway returned an incomplete response.',
                'reference': reference,
            },
            status=status.HTTP_502_BAD_GATEWAY
        )

    if returned_reference != reference:
        with transaction.atomic():
            payment = (
                Payment.objects
                .select_for_update()
                .get(pk=payment.pk)
            )

            # Do not overwrite a payment that may already have been
            # confirmed by a webhook while the gateway response arrived.
            if payment.status == 'pending':
                payment.provider_reference = returned_reference
                payment.save(
                    update_fields=['provider_reference']
                )

    return Response(
        {
            'authorization_url': data['authorization_url'],
            'reference': returned_reference,
        },
        status=status.HTTP_200_OK
    )

# ============================================================
# PAYSTACK M-PESA CHARGE
# ============================================================

class MpesaPushThrottle(SimpleRateThrottle):
    """Each M-PESA initialization pushes a prompt to a phone: limit it per user."""
    scope = 'mpesa_push'

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': request.user.pk}


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([MpesaPushThrottle])
def initialize_mpesa_payment(request, booking_id):
    """Send one Paystack M-PESA charge for the passenger's booking."""
    _release_dead_digital_attempt(booking_id, request.user)

    try:
        with transaction.atomic():
            booking = (
                Booking.objects
                .select_for_update()
                .get(
                    id=booking_id,
                    user=request.user,
                )
            )

            if booking.status in (
                'cancelled',
                'completed',
                'no_show',
            ):
                return Response(
                    {'error': 'This booking cannot be paid for.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if trip_has_departed(booking.trip):
                return Response(
                    {'error': 'This trip has already departed.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            tampered = _tampered_amount(request, booking.total_amount)
            if tampered is not None:
                return tampered

            phone = (
                request.data.get('phone_number')
                or booking.user.phone_number
            )

            if not phone:
                return Response(
                    {'error': 'Enter an M-PESA phone number.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                phone = kenyan_mobile(phone)
            except DjangoValidationError as e:
                return Response(
                    {'error': 'M-PESA: ' + e.messages[0]},
                    status=status.HTTP_400_BAD_REQUEST
                )

            existing = (
                Payment.objects
                .select_for_update()
                .filter(booking=booking)
                .first()
            )

            if existing and existing.status == 'confirmed':
                return Response(
                    {
                        'error':
                            'This booking has already been paid for.'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if (
                existing
                and existing.status == 'pending'
                and existing.method == 'digital'
                and existing.provider_reference
            ):
                return Response(
                    {
                        'error': (
                            'A digital payment is already in progress '
                            'for this booking.'
                        ),
                        'reference': existing.provider_reference,
                    },
                    status=status.HTTP_409_CONFLICT
                )

            reference = (
                f'CONNECT-{booking.id}-{uuid.uuid4().hex}'
            )

            if existing:
                payment = existing
                payment.amount = booking.total_amount
                payment.method = 'digital'
                payment.status = 'pending'
                payment.settlement_status = 'not_ready'
                payment.provider_reference = reference
                payment.idempotency_key = reference
                payment.confirmed_at = None
                payment.refunded_at = None
                payment.refund_reference = None
                payment.refund_status = 'not_requested'
                payment.refund_reason = ''
                payment.paid_amount = None
                payment.save(
                    update_fields=[
                        'amount',
                        'method',
                        'status',
                        'settlement_status',
                        'provider_reference',
                        'idempotency_key',
                        'confirmed_at',
                        'refunded_at',
                        'refund_reference',
                        'refund_status',
                        'refund_reason',
                        'paid_amount',
                    ]
                )
            else:
                payment = Payment.objects.create(
                    booking=booking,
                    amount=booking.total_amount,
                    method='digital',
                    status='pending',
                    settlement_status='not_ready',
                    provider_reference=reference,
                    idempotency_key=reference,
                )

    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    amount_in_cents = int(
        booking.total_amount * Decimal('100')
    )

    headers = {
        'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json',
    }

    payload = {
        'email': (
            request.user.email
            if request.user.email and '@' in request.user.email
            and '.' in request.user.email.split('@')[-1]
            and ' ' not in request.user.email
            else f'user_{request.user.id}@example.com'
        ),
        'amount': amount_in_cents,
        'currency': 'KES',
        'reference': reference,
        'mobile_money': {
            'phone': phone,
            'provider': 'mpesa',
        },
        'metadata': {
            'booking_id': booking.id,
            'user_id': request.user.id,
            'channel': 'mpesa',
        },
    }

    try:
        gateway_response = requests.post(
            'https://api.paystack.co/charge',
            json=payload,
            headers=headers,
            timeout=30,
        )
    except requests.RequestException:
        return Response(
            {
                'error': (
                    'Unable to confirm the M-PESA gateway request. '
                    'Check the payment status before retrying.'
                ),
                'reference': reference,
            },
            status=status.HTTP_502_BAD_GATEWAY
        )

    try:
        result = gateway_response.json()
    except ValueError:
        return Response(
            {
                'error': 'Invalid response from Paystack.',
                'reference': reference,
            },
            status=status.HTTP_502_BAD_GATEWAY
        )

    if gateway_response.status_code != 200 or not result.get('status'):
        # Paystack answered and refused, so no prompt was sent: release the
        # attempt so the passenger can retry. A 5xx or timeout stays
        # "in progress" because the prompt may already be on the phone.
        if gateway_response.status_code < 500:
            Payment.objects.filter(pk=payment.pk, status='pending').update(
                status='failed')
        return Response(
            {
                'error': result.get(
                    'message',
                    'Unable to start M-PESA payment.'
                ),
                'reference': reference,
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    data = result.get('data') or {}
    returned_reference = data.get('reference')

    if not returned_reference:
        return Response(
            {
                'error':
                    'Paystack did not return a payment reference.',
                'reference': reference,
            },
            status=status.HTTP_502_BAD_GATEWAY
        )

    if returned_reference != reference:
        with transaction.atomic():
            payment = (
                Payment.objects
                .select_for_update()
                .get(pk=payment.pk)
            )

            if payment.status == 'pending':
                payment.provider_reference = returned_reference
                payment.save(
                    update_fields=['provider_reference']
                )

    return Response(
        {
            'booking_id': booking.id,
            'reference': returned_reference,
            'status': data.get('status', 'pay_offline'),
            'display_text': data.get(
                'display_text',
                (
                    'Please check your phone and complete '
                    'the M-PESA authorization.'
                ),
            ),
            'phone': phone,
            'amount': str(booking.total_amount),
        },
        status=status.HTTP_200_OK,
    )

# ============================================================
# PAYMENT STATUS / VERIFY
# ============================================================

def _push_booked(booking):
    """Phone alert once the seat is paid. After commit, so a rollback sends nothing.
    Never lets an alert problem fail the payment."""
    try:
        trip = booking.trip
        if trip is None:
            return
        when = timezone.localtime(trip.departure_at).strftime('%a %d %b, %H:%M')
        title, body = 'Seat booked', f'{trip.route.name}, {when}. We will alert you when the bus is boarding.'
        transaction.on_commit(lambda: push.notify_users(
            [booking.user_id], title, body, url='/passenger', tag=f'booking-{booking.id}-booked'))
    except Exception:
        logging.getLogger(__name__).exception('booking %s: seat-booked alert not queued', booking.id)


def _finish_confirm(outcome, send_refunds=True):
    """
    Side effects of confirm_booking_payment that need no open transaction.

    send_refunds=False is for a GET: it never calls the refund endpoint. The
    refund is already recorded (Payment.refund_reason, or a refund_due row)
    and the process_noshows / process_unapplied sweeps send it.
    """
    if outcome.result == 'confirmed':
        _push_booked(outcome.booking)
    if outcome.result == 'rejected' and outcome.alert:
        _alert_payment_problem(*outcome.alert)
    elif outcome.result == 'refund' and send_refunds:
        payment = outcome.payment
        try:
            settle_booking_fault(outcome.booking, fault_party='company')
        except Exception:
            _alert_payment_problem(
                payment.provider_reference,
                'late payment confirmed but the automatic refund failed',
            )
    from connect import paystack_extra as px
    for row in outcome.extra_refunds:
        try:
            if row.status == 'review':
                px._alert(
                    f'Payment {row.reference}: overpaid by KES {row.amount}, '
                    f'below the refund minimum. Refund manually.')
            elif send_refunds and px.claim_refund(row):
                row.refresh_from_db()
                px.send_refund(row)
        except Exception:
            logging.getLogger(__name__).exception(
                'Overpayment refund for %s failed', row.reference)
    return outcome


class PaymentStatusThrottle(SimpleRateThrottle):
    """The status poll can call Paystack synchronously: limit it per user."""
    scope = 'payment_status'
    # Class-level so settings.py needs no DEFAULT_THROTTLE_RATES entry.
    rate = '30/min'

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': request.user.pk}


class PaymentVerifyThrottle(PaymentStatusThrottle):
    scope = 'payment_verify'
    rate = '20/min'


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([UserRateThrottle, PaymentStatusThrottle])
def payment_status(request, booking_id):
    try:
        payment = Payment.objects.select_related('booking').get(
            booking_id=booking_id,
            booking__user=request.user,
        )
    except Payment.DoesNotExist:
        return Response({
            'booking_id': booking_id,
            'payment_status': 'unpaid',
            'payment_method': None,
        })

    # Automatically verify pending Paystack payments.
    if (
        payment.status == 'pending'
        and payment.method == 'digital'
        and payment.provider_reference
    ):
        headers = {
            'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
        }

        gateway_response = None
        try:
            gateway_response = requests.get(
                f'https://api.paystack.co/transaction/verify/{payment.provider_reference}',
                headers=headers,
                timeout=getattr(
                    settings, 'PAYMENT_STATUS_VERIFY_TIMEOUT_SECONDS', 10),
            )
            result = gateway_response.json()
        except (requests.RequestException, ValueError):
            result = {}

        data = result.get('data') or {}

        if (
            gateway_response is not None
            and gateway_response.status_code == 200
            and result.get('status')
            and data.get('status') == 'success'
            # No amount in the answer: cannot judge it, so leave the payment
            # pending for the signed webhook instead of flagging a charge
            # that may be valid.
            and data.get('amount') not in (None, '', 0, '0')
        ):
            _finish_confirm(confirm_booking_payment(
                payment_id=payment.pk,
                paid_amount=data.get('amount', 0),
                currency=data.get('currency'),
            ), send_refunds=False)
            payment.refresh_from_db()
            payment.booking.refresh_from_db()

    return Response({
        'booking_id': booking_id,
        'payment_id': payment.id,
        'payment_status': payment.status,
        'payment_method': payment.method,
        'settlement_status': payment.settlement_status,
        'reference': payment.provider_reference,
        'amount': str(payment.amount),
        'confirmed_at': payment.confirmed_at,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([UserRateThrottle, PaymentVerifyThrottle])
def verify_paystack_payment(request, booking_id):
    """Verify a Paystack transaction after a hosted checkout return."""
    try:
        payment = Payment.objects.select_related('booking').get(
            booking_id=booking_id,
            booking__user=request.user,
        )
    except Payment.DoesNotExist:
        return Response({'error': 'Payment not found.'}, status=404)

    if payment.status == 'confirmed':
        return Response({'payment_status': 'confirmed', 'booking_status': payment.booking.status})

    if not payment.provider_reference:
        return Response({'error': 'No Paystack reference exists for this booking.'}, status=400)

    headers = {'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}'}
    try:
        gateway_response = requests.get(
            f"https://api.paystack.co/transaction/verify/{payment.provider_reference}",
            headers=headers,
            timeout=30,
        )
    except requests.RequestException:
        return Response({'error': 'Unable to connect to Paystack.'}, status=502)

    try:
        result = gateway_response.json()
    except ValueError:
        return Response({'error': 'Invalid response from Paystack.'}, status=502)

    data = result.get('data') or {}
    if gateway_response.status_code != 200 or not result.get('status'):
        return Response(
            {'error': result.get('message', 'Payment verification failed.')},
            status=400,
        )

    # No amount in the answer: leave it pending for the signed webhook.
    if data.get('status') == 'success' and data.get('amount') not in (None, '', 0, '0'):
        outcome = _finish_confirm(confirm_booking_payment(
            payment_id=payment.pk,
            paid_amount=data.get('amount', 0),
            currency=data.get('currency'),
        ))
        if outcome.result == 'retry':
            return Response(
                {'error': 'This booking changed trips. Please try again.'},
                status=status.HTTP_409_CONFLICT,
            )
        payment.refresh_from_db()
        payment.booking.refresh_from_db()
        return Response({'payment_status': payment.status, 'booking_status': payment.booking.status})

    return Response({
        'payment_status': data.get('status', payment.status),
        'message': data.get('gateway_response') or data.get('message') or 'Payment is still pending.',
    })


# ============================================================
# PAYSTACK WEBHOOK
# ============================================================

def _alert_payment_problem(reference, reason):
    """Log and SMS the admins about money that needs a human. Never raises."""
    import logging

    log = logging.getLogger(__name__)
    log.error('Paystack payment %s needs attention: %s', reference, reason)
    try:
        send_admin_alert_sms(
            f'Payment {reference}: {reason}. Check Paystack; refund manually if needed.'
        )
    except Exception:
        log.exception('Admin alert failed for %s', reference)


def _signed_event(body):
    """The JSON object in a signed webhook body, or None when it is not one."""
    try:
        event = json.loads(body.decode('utf-8'))
    except (ValueError, RecursionError):
        return None
    return event if isinstance(event, dict) else None


@csrf_exempt
@require_POST
def paystack_webhook(request):
    signature = request.headers.get('X-Paystack-Signature')

    if not signature:
        return HttpResponse(status=400)

    body = request.body

    computed_signature = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode('utf-8'),
        body,
        hashlib.sha512
    ).hexdigest()

    if not hmac.compare_digest(signature.encode('utf-8'), computed_signature.encode('utf-8')):
        return HttpResponse(status=400)

    event = _signed_event(body)
    if event is None:
        return HttpResponse(status=400)

    # Wallet top-up charges carry a TOPUP- reference and must never reach the
    # booking lookup below (it would refund them as an unknown booking). An
    # error is answered 500 so Paystack delivers the event again.
    from wallets.webhook import handle_event
    try:
        if handle_event(event):
            return HttpResponse(status=200)
    except Exception:
        logging.getLogger(__name__).exception('wallet webhook handler failed')
        return HttpResponse(status=500)

    # Paystack allows ONE webhook URL per mode, so refund events arrive here.
    # The refund handler re-verifies the signature itself.
    if str(event.get('event', '')).startswith('refund.'):
        return paystack_refund_webhook(request)

    if event.get('event') != 'charge.success':
        return HttpResponse(status=200)

    data = event.get('data')
    data = data if isinstance(data, dict) else {}
    reference = data.get('reference')

    if not reference or not isinstance(reference, str):
        return HttpResponse(status=400)

    # Parcel and bus-hire payments carry their own references.
    from connect.paystack_extra import handle_extra_charge
    if handle_extra_charge(reference, data):
        return HttpResponse(status=200)

    outcome = confirm_booking_payment(
        reference=reference,
        paid_amount=data.get('amount'),
        currency=data.get('currency'),
    )

    if outcome.result == 'not_found':
        # Unknown references must not cause endless Paystack retries, but a
        # signed successful charge we cannot match is real money. One of our
        # own references is refunded in full (once: the row's reference is
        # unique); anything else is alerted for a human.
        try:
            row, created = record_unmatched_charge(
                reference, data.get('amount'), data.get('currency'))
        except Exception:
            # Not recorded: answer non-200 so Paystack resends (safe: the
            # reference is unique).
            logging.getLogger(__name__).exception(
                'Could not record unmatched charge %s', reference)
            _alert_payment_problem(reference, 'unmatched booking charge NOT recorded yet')
            return HttpResponse(status=500)
        if row is None:
            _alert_payment_problem(
                reference, 'charge.success for an unknown reference')
        elif created:
            # Never refunded inline: the webhook stays fast and
            # process_unapplied sends the refund (one winner, never twice).
            if row.status == 'refund_due':
                _alert_payment_problem(
                    reference,
                    f'matches no booking payment: KES {row.amount} is queued '
                    'for automatic refund')
            else:
                _alert_payment_problem(
                    reference,
                    'charge.success matches no booking payment and its '
                    'amount or currency is unusable')
        return HttpResponse(status=200)

    if outcome.result == 'retry':
        # The booking moved trips while we waited for its locks. Nothing was
        # changed; a 500 makes Paystack deliver the event again.
        return HttpResponse(status=500)

    # A refund or alert runs here, after the confirming transaction has
    # committed, because it calls Paystack or SMS.
    _finish_confirm(outcome)
    return HttpResponse(status=200)


# ============================================================
# PAYSTACK REFUND WEBHOOK
# ============================================================

REFUND_EVENT_STATUS_MAP = {
    'refund.pending': 'pending',
    'refund.processing': 'processing',
    'refund.processed': 'processed',
    'refund.failed': 'failed',
}


def _route_refund_event(transaction_reference, data, new_refund_status):
    """
    One charge can carry two refunds: the booking refund (Payment) and an
    overpayment's difference (UnappliedPayment). Decide which one a refund
    event is about. The stored refund id wins; the amount is only a fallback;
    if it is still unclear nothing is touched and an admin is alerted once.

    Returns True when the event was handled here, False when the charge has no
    UnappliedPayment row and the caller should use the plain Payment path.
    """
    from connect import paystack_extra as px
    from .models import UnappliedPayment

    # Which field carries Paystack's refund id in the event is UNVERIFIED, so
    # either is matched against the id stored when the refund was sent.
    ids = [
        str(v) for v in (data.get('refund_reference'), data.get('id'))
        if v not in (None, '')
    ]
    try:
        event_amount = int(data['amount']) if data.get('amount') is not None else None
    except (TypeError, ValueError, OverflowError):
        event_amount = None

    def fits(stored_id, stored_amount):
        if ids and stored_id:
            return stored_id in ids
        if event_amount is not None and stored_amount is not None:
            return int(stored_amount * 100) == event_amount
        return True

    with transaction.atomic():
        payment = (
            Payment.objects.select_for_update()
            .filter(provider_reference=transaction_reference).first()
        )
        rows = list(
            UnappliedPayment.objects.select_for_update()
            .filter(reference=transaction_reference,
                    status__in=('refunding', 'refunded'))
        )
        if not rows:
            return False

        row_by_id = next(
            (r for r in rows if r.refund_reference and r.refund_reference in ids),
            None)
        pay_by_id = bool(
            payment is not None and payment.refund_reference
            and payment.refund_reference in ids)
        if row_by_id is not None and not pay_by_id:
            target = row_by_id
        elif pay_by_id and row_by_id is None:
            return False
        else:
            candidates = [r for r in rows if fits(r.refund_reference, r.amount)]
            pay_fits = (
                payment is not None
                and payment.refund_status != 'not_requested'
                and fits(payment.refund_reference, payment.refund_amount)
            )
            if len(candidates) + (1 if pay_fits else 0) != 1:
                key = (f'refund-ambiguous:{transaction_reference}:'
                       f'{new_refund_status}:{ids}:{event_amount}')
                if cache.add(key, 1, 24 * 60 * 60):
                    ambiguous_alert = (
                        f'Refund event for {transaction_reference} '
                        f'(amount {event_amount}) cannot be matched to one '
                        f'refund. Nothing was changed; check Paystack.'
                    )
                    # After commit: no SMS call while the rows are locked.
                    transaction.on_commit(lambda: px._alert(ambiguous_alert))
                return True
            if pay_fits:
                return False
            target = candidates[0]

        if target.refund_status == 'processed':
            return True
        fields = {'refund_status': new_refund_status}
        if new_refund_status == 'failed':
            fields.update(status='review', reason='refund failed at Paystack')
        else:
            fields['status'] = 'refunded'
        if not target.refund_reference and ids:
            fields['refund_reference'] = ids[0][:100]
        UnappliedPayment.objects.filter(pk=target.pk).update(
            updated_at=timezone.now(), **fields)
        if new_refund_status == 'failed':
            failed_reason = (
                f'automatic refund of KES {target.amount} FAILED at Paystack: '
                f'refund manually')
            transaction.on_commit(
                lambda: _alert_payment_problem(target.reference, failed_reason))
    return True


@csrf_exempt
@require_POST
def paystack_refund_webhook(request):
    signature = request.headers.get('X-Paystack-Signature')

    if not signature:
        return HttpResponse(status=400)

    body = request.body

    computed_signature = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode('utf-8'),
        body,
        hashlib.sha512
    ).hexdigest()

    if not hmac.compare_digest(signature.encode('utf-8'), computed_signature.encode('utf-8')):
        return HttpResponse(status=400)

    event = _signed_event(body)
    if event is None:
        return HttpResponse(status=400)

    event_type = event.get('event')
    new_refund_status = REFUND_EVENT_STATUS_MAP.get(event_type)

    if new_refund_status is None:
        # Not a refund event we care about.
        return HttpResponse(status=200)

    data = event.get('data')
    data = data if isinstance(data, dict) else {}
    transaction_reference = data.get('transaction_reference')

    if not transaction_reference or not isinstance(transaction_reference, str):
        return HttpResponse(status=400)

    if _route_refund_event(transaction_reference, data, new_refund_status):
        return HttpResponse(status=200)

    try:
        with transaction.atomic():
            payment = (
                Payment.objects
                .select_for_update()
                .get(provider_reference=transaction_reference)
            )

            # An event about another refund (a redelivery for one that was
            # superseded by a retry) must not touch this one.
            event_ids = [
                str(v) for v in (data.get('refund_reference'), data.get('id'))
                if v not in (None, '')
            ]
            if event_ids and payment.refund_reference:
                if payment.refund_reference not in event_ids:
                    # Dropped silently, so tell an admin once a day per payment.
                    if cache.add(f"refund-event-dropped:{payment.pk}", 1, 24 * 60 * 60):
                        dropped_alert = (
                            f"Refund event dropped for payment #{payment.pk}: "
                            f"it does not match the stored refund "
                            f"{payment.refund_reference}."
                        )
                        transaction.on_commit(
                            lambda: send_admin_alert_sms(dropped_alert)
                        )
                    return HttpResponse(status=200)
            elif (
                event_ids and new_refund_status == 'failed'
                and payment.refund_status == 'processing'
            ):
                # The retry has been claimed but Paystack's answer is not
                # recorded yet, so this cannot be told from a stale event.
                # reconcile_refunds flags a failed status for a human.
                return HttpResponse(status=200)

            # A processed refund is final and must never be
            # downgraded by a later/duplicate webhook.
            already_processed = payment.refund_status == 'processed'

            if not already_processed:
                update_fields = ['refund_status']
                payment.refund_status = new_refund_status

                refund_reference = data.get('refund_reference')

                if refund_reference and not payment.refund_reference:
                    payment.refund_reference = str(refund_reference)
                    update_fields.append('refund_reference')

                if new_refund_status == 'processed':
                    # Money genuinely reached the passenger.
                    payment.refunded_at = timezone.now()
                    update_fields.append('refunded_at')
                    # Only a full refund closes the payment. A partial
                    # refund stays 'confirmed' so settle_company pays the
                    # company the remainder.
                    if (
                        payment.refund_amount is not None
                        and payment.refund_amount >= payment.amount
                    ):
                        payment.status = 'refunded'
                        update_fields.append('status')

                # A failed refund means the reversal did not reach the
                # passenger. The original charge remains confirmed.
                #
                # This MUST be surfaced to an administrator instead of
                # silently disappearing.
                if new_refund_status == 'failed':
                    # After commit: no SMS call while the payment row is locked.
                    failed_alert = (
                        f"Refund FAILED for booking "
                        f"{payment.booking.booking_number} "
                        f"(payment #{payment.id}, amount "
                        f"{payment.refund_amount}). "
                        f"Paystack could not process the reversal - "
                        f"needs manual follow-up."
                    )
                    transaction.on_commit(
                        lambda: send_admin_alert_sms(failed_alert)
                    )

                payment.save(update_fields=update_fields)

            # Finalize the internal hold when Paystack confirms the
            # refund. This is idempotent across duplicate webhooks.
            if (
                new_refund_status == 'processed'
                and payment.refund_amount is not None
            ):
                hold = (
                    BookingHold.objects
                    .select_for_update()
                    .filter(booking_id=payment.booking_id)
                    .first()
                )

                if hold is not None:
                    target_refunded_amount = payment.refund_amount

                    # Repair only a missing allocation. Never add the
                    # same refund twice.
                    if hold.refunded_amount < target_refunded_amount:
                        hold.refunded_amount = target_refunded_amount

                    if (
                        hold.refunded_amount >= hold.amount
                        and hold.status != 'refunded'
                    ):
                        hold.status = 'refunded'
                        hold.refunded_at = timezone.now()

                        hold.save(
                            update_fields=[
                                'refunded_amount',
                                'status',
                                'refunded_at',
                                'updated_at',
                            ]
                        )
                    else:
                        hold.save(
                            update_fields=[
                                'refunded_amount',
                                'updated_at',
                            ]
                        )

    except Payment.DoesNotExist:
        # Unknown transaction reference should not cause retries.
        return HttpResponse(status=200)

    return HttpResponse(status=200)


# ============================================================
# WALLET PAYMENT
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pay_from_wallet(request, booking_id):
    """
    Pay a pending booking from the passenger's wallet. No gateway call; the
    debit and the confirmation are one transaction. Calling it again on a
    booking that is already wallet-paid returns the same 200.
    """
    from wallets.models import Wallet
    from wallets.services import InsufficientFunds

    echoed = [
        request.data.get(f) for f in ('amount', 'total_amount')
        if request.data.get(f) not in (None, '')
    ]
    try:
        booking, payment, replayed = pay_booking_from_wallet(
            booking_id, request.user, echoed)
    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
    except WalletPayRefused as exc:
        return Response(
            {'error': str(exc), 'code': exc.code, **exc.extra},
            status=exc.http_status)
    except InsufficientFunds:
        balance = (
            Wallet.objects.filter(user=request.user)
            .values_list('available_balance', flat=True).first()
            or Decimal('0.00')
        )
        required = (
            Booking.objects.filter(pk=booking_id, user=request.user)
            .values_list('total_amount', flat=True).first()
        )
        return Response(
            {
                'error': 'Your wallet balance is too low for this booking.',
                'code': 'insufficient_funds',
                'balance': str(balance),
                'required': str(required),
            },
            status=status.HTTP_400_BAD_REQUEST)

    if not replayed:
        _push_booked(booking)
    balance = Wallet.objects.get(user=request.user).available_balance
    return Response(
        {
            'message': 'Booking paid from your wallet.',
            'booking_id': booking.id,
            'payment_id': payment.id,
            'amount': str(payment.amount),
            'method': payment.method,
            'status': payment.status,
            'booking_status': booking.status,
            'balance': str(balance),
            'replayed': replayed,
        },
        status=status.HTTP_200_OK)


# ============================================================
# CASH PAYMENT INITIALIZATION
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def initialize_cash_payment(request, booking_id):
    """
    Select cash payment for a booking exactly once.

    The booking row is locked before inspecting/creating the Payment.
    This serializes simultaneous cash-payment requests for the same
    booking and prevents OneToOne races.
    """
    if not request.user.can_pay_cash:
        return Response(
            {
                'error': (
                    'Cash on board is not available yet. Pay with M-Pesa or card.'
                    if not settings.CASH_ENABLED else
                    'Cash on board is for regular riders: '
                    f'{settings.CASH_MIN_TRIPS} trips, an integrity score of '
                    f'{settings.CASH_MIN_INTEGRITY:g}% or more and an account at least '
                    f'{settings.CASH_MIN_ACCOUNT_DAYS} days old. Pay with M-Pesa or card for now.'
                ),
                'code': 'cash_locked',
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    _release_dead_digital_attempt(booking_id, request.user)

    try:
        with transaction.atomic():
            # Trip first, then Booking (the order cancel_booking uses).
            trip, booking = lock_trip_then_booking(
                booking_id, user=request.user)

            if booking.status in (
                'cancelled',
                'completed',
                'no_show',
            ):
                return Response(
                    {
                        'error': (
                            'Cannot pay for booking with status: '
                            f'{booking.status}'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if trip_has_departed(booking.trip):
                return Response(
                    {
                        'error': (
                            'This trip has already departed. '
                            'Payment can no longer be made.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            tampered = _tampered_amount(request, booking.total_amount)
            if tampered is not None:
                return tampered

            payment = (
                Payment.objects
                .select_for_update()
                .filter(booking=booking)
                .first()
            )

            if payment and payment.status == 'confirmed':
                return Response(
                    {'error': 'This booking has already been paid for'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if payment and payment.status == 'refunded':
                return Response(
                    {'error': 'This booking payment has already been refunded'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if (
                payment
                and payment.method == 'digital'
                and payment.status == 'pending'
            ):
                return Response(
                    {
                        'error': (
                            'Digital payment already started '
                            'for this booking'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if booking.status == 'pending':
                # The one extension a hold ever gets: cash is paid on board,
                # possibly at a later stage, so the seat is held until the
                # trip is over. Computed from the departure time, so
                # repeating this call never moves it again.
                cash_until = (
                    trip.departure_at + timedelta(
                        hours=getattr(settings, 'TRIP_AUTO_CLOSE_AFTER_HOURS', 12))
                    if trip is not None else booking.held_until
                )
                if hold_expired_and_seat_gone(booking, trip):
                    return Response(
                        {
                            'error': (
                                'The time to hold this booking has run out.'
                            ),
                            'code': 'hold_expired',
                        },
                        status=status.HTTP_409_CONFLICT
                    )
                if cash_until is not None and (
                    booking.held_until is None or cash_until > booking.held_until
                ):
                    booking.held_until = cash_until
                    booking.save(update_fields=['held_until'])
                # A lapsed hold had its seat rows purged; the capacity check
                # above passed under this lock, so the numbers are free again.
                if trip is not None:
                    ensure_numbers(trip, booking)

            if payment is None:
                payment = Payment.objects.create(
                    booking=booking,
                    amount=booking.total_amount,
                    method='cash',
                    status='pending',
                    settlement_status='not_ready',
                    provider_reference=None,
                    idempotency_key=None,
                    refund_status='not_requested',
                )
            else:
                payment.amount = booking.total_amount
                payment.method = 'cash'
                payment.status = 'pending'
                payment.settlement_status = 'not_ready'
                payment.provider_reference = None
                payment.idempotency_key = None
                payment.confirmed_at = None
                payment.refunded_at = None
                payment.refund_reference = None
                payment.refund_status = 'not_requested'
                payment.refund_reason = ''
                payment.paid_amount = None
                payment.refund_amount = None
                payment.save(
                    update_fields=[
                        'amount',
                        'method',
                        'status',
                        'settlement_status',
                        'provider_reference',
                        'idempotency_key',
                        'confirmed_at',
                        'refunded_at',
                        'refund_reference',
                        'refund_status',
                        'refund_reason',
                        'paid_amount',
                        'refund_amount',
                    ]
                )

            return Response(
                {
                    'message': (
                        'Cash payment selected. '
                        'Pay the conductor/driver to confirm.'
                    ),
                    'booking_id': booking.id,
                    'payment_id': payment.id,
                    'amount': str(payment.amount),
                    'method': payment.method,
                    'status': payment.status,
                },
                status=status.HTTP_200_OK
            )

    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except BookingMoved:
        return Response(
            {'error': 'This booking changed trips. Please try again.'},
            status=status.HTTP_409_CONFLICT
        )


# ============================================================
# CASH PAYMENT CONFIRMATION
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def confirm_cash_payment(request, booking_id):
    try:
        with transaction.atomic():
            # IMPORTANT:
            # Do NOT use select_related() here.
            #
            # Booking.trip is nullable. PostgreSQL rejects
            # SELECT ... FOR UPDATE when Django generates an
            # outer join to a nullable relation.
            #
            # Lock only the Booking row. Related objects are
            # fetched separately below.
            trip, booking = lock_trip_then_booking(booking_id)

            user = request.user

            # Cash payment confirmation is allowed for:
            # - Django superusers
            # - Company Managers for their own company
            # - The driver assigned to this booking's trip
            # - Company Operators only if OPERATORS_CAN_CONFIRM_CASH is on
            #   (off by default: money is not an operator job)
            #
            # Company Auditors are read-only.
            # Generic is_staff=True does not grant payment authority.
            from django.conf import settings as _dj_settings
            _cash_roles = {'company_manager'}
            if getattr(_dj_settings, 'OPERATORS_CAN_CONFIRM_CASH', False):
                _cash_roles.add('company_operator')
            is_authorized = (
                user.is_superuser
                or (
                    user.role in _cash_roles
                    and user.company_id == booking.route.company_id
                    and can_handle_route(user, booking.route_id)
                )
            )

            # Driver assigned to this trip may confirm
            # the cash payment.
            if (
                not is_authorized
                and booking.trip
                and booking.trip.driver
            ):
                # A phone match alone is not identity: see users/identity.py
                # (driver role + same phone + same company, never a blank phone).
                if (
                    is_driver_account_for(user, booking.trip.driver)
                    and user.company_id in (None, booking.route.company_id)
                ):
                    is_authorized = True

            if not is_authorized:
                return _not_yours(user, booking)

            try:
                payment = (
                    Payment.objects
                    .select_for_update()
                    .get(booking=booking)
                )
            except Payment.DoesNotExist:
                return Response(
                    {'error': 'Payment record not found.'},
                    status=status.HTTP_404_NOT_FOUND
                )

            if payment.method != 'cash':
                return Response(
                    {'error': 'Payment method is not cash.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if payment.status == 'confirmed':
                return Response(
                    {
                        'message': (
                            'Cash payment already confirmed.'
                        )
                    },
                    status=status.HTTP_200_OK
                )

            if booking.status in ('cancelled', 'completed', 'no_show'):
                return Response(
                    {'error': f'Cannot confirm cash for a {booking.status} booking.'},
                    status=status.HTTP_409_CONFLICT,
                )

            if not cash_still_payable(booking.trip):
                return Response(
                    {
                        'error': (
                            'This trip has already departed. '
                            'Payment can no longer be confirmed.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # The hold ran out and the seat has been resold: confirming
            # would oversell the trip. The operator boards a walk-up instead.
            if hold_expired_and_seat_gone(booking, trip):
                return Response(
                    {
                        'error': (
                            'The time to hold this booking has run out and '
                            'its seats are taken. Board a walk-up passenger '
                            'instead.'
                        ),
                        'code': 'hold_expired',
                    },
                    status=status.HTTP_409_CONFLICT
                )

            # -------------------------------------------------
            # CASH CONFIRMED
            # -------------------------------------------------
            #
            # Cash must NOT increase the passenger's digital
            # wallet balance or held balance.
            #
            # Cash is tracked through Payment and later
            # reconciled against the trip/company's collection.

            payment.status = 'confirmed'
            payment.settlement_status = 'not_ready'
            payment.confirmed_at = timezone.now()

            payment.save(
                update_fields=[
                    'status',
                    'settlement_status',
                    'confirmed_at',
                ]
            )

            booking.status = 'confirmed'
            booking.save(update_fields=['status'])
            if trip is not None:
                ensure_numbers(trip, booking)
            _push_booked(booking)

            return Response(
                {
                    'message': (
                        'Cash payment confirmed. '
                        'Cash will be reconciled separately.'
                    ),
                    'payment_id': payment.id,
                    'booking_id': booking.id,
                    'amount': str(payment.amount),
                    'method': payment.method,
                    'status': payment.status,
                },
                status=status.HTTP_200_OK
            )

    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found.'},
            status=status.HTTP_404_NOT_FOUND
        )
    except BookingMoved:
        return Response(
            {'error': 'This booking changed trips. Please try again.'},
            status=status.HTTP_409_CONFLICT
        )


# ============================================================
# CREATE BOOKING
# ============================================================

def _seat_limit(message):
    return Response(
        {'error': message, 'code': 'seat_limit'},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _booking_created_payload(booking):
    return {
        'message': (
            'Booking created successfully. '
            'Proceed to payment.'
        ),
        'booking_id': booking.id,
        'booking_number': booking.booking_number,
        'seat_numbers': sorted(
            booking.seat_assignments.values_list('seat_no', flat=True)),
        'total_amount': str(booking.total_amount),
        'pay_before': booking.held_until,
        'pickup_location': booking.pickup_location,
        'pickup_stage_id': (
            booking.pickup_stage_id
            if booking.pickup_stage_id
            else None
        ),
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_booking(request):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    if not str(request.data.get('seats', '1')).isascii():
        return Response(
            {'seats': ['A valid integer is required.']},
            status=status.HTTP_400_BAD_REQUEST
        )

    serializer = BookingCreateSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    validated_data = serializer.validated_data
    trip_id = validated_data['trip_id']
    seats = validated_data['seats']
    if seats > settings.MAX_SEATS_PER_BOOKING:
        return _seat_limit(
            f'You can book at most {settings.MAX_SEATS_PER_BOOKING} seats at a time.')
    pickup_stage_id = validated_data.get('pickup_stage_id')
    legacy_pickup_location = validated_data.get(
        'pickup_location',
        ''
    ).strip()
    idempotency_key = validated_data.get('idempotency_key') or None
    picked = sorted(validated_data.get('seat_numbers') or [])
    fingerprint = hashlib.sha256(
        f'{trip_id}|{seats}|{pickup_stage_id or ""}|{legacy_pickup_location}|{picked}'
        .encode('utf-8')
    ).hexdigest()

    try:
        with transaction.atomic():
            # of=('self',): lock only the Trip row, never the Route/Company
            # rows joined in by select_related.
            trip = (
                Trip.objects
                .select_for_update(of=('self',))
                .select_related('route')
                .get(id=trip_id)
            )

            if idempotency_key:
                # A repeat of an earlier request returns that booking, so it
                # must be answered before the seat, cap and cut-off checks
                # that the first booking itself now affects. The user row
                # lock makes two simultaneous repeats take turns.
                from django.contrib.auth import get_user_model
                get_user_model().objects.select_for_update().get(
                    pk=request.user.pk)
                first = Booking.objects.filter(
                    user=request.user, idempotency_key=idempotency_key
                ).first()
                if first is not None:
                    if first.idempotency_fingerprint != fingerprint:
                        return Response(
                            {
                                'error': (
                                    'This idempotency_key was already used '
                                    'for a different booking request.'
                                ),
                                'code': 'idempotency_key_reused',
                            },
                            status=status.HTTP_409_CONFLICT
                        )
                    payload = _booking_created_payload(first)
                    payload['replayed'] = True
                    payload['status'] = first.status
                    return Response(payload, status=status.HTTP_200_OK)

            if trip.status not in ('scheduled', 'boarding'):
                return Response(
                    {
                        'error': (
                            'Cannot book trips that are not '
                            'scheduled or have already departed.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            now = timezone.now()
            closes_at = booking_closes_at(trip)
            if now >= closes_at:
                return Response(
                    {
                        'error': 'Online booking for this trip has closed.',
                        'code': 'booking_closed',
                        'closes_at': closes_at,
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            pickup_stage = None

            if pickup_stage_id is not None:
                try:
                    pickup_stage = PickupStage.objects.get(
                        id=pickup_stage_id,
                        route_id=trip.route_id,
                        is_active=True,
                    )
                except PickupStage.DoesNotExist:
                    return Response(
                        {
                            'error': (
                                'Selected pickup stage does not '
                                'belong to this trip route or is inactive.'
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # The last stage is where the trip ends: riders get off
                # there, so it cannot be where one gets on.
                _stage_ids = list(
                    PickupStage.objects
                    .filter(route_id=trip.route_id, is_active=True)
                    .order_by('order', 'id')
                    .values_list('id', flat=True)
                )
                if len(_stage_ids) > 1 and pickup_stage.id == _stage_ids[-1]:
                    return Response(
                        {
                            'error': (
                                f'{pickup_stage.name} is where this trip '
                                'ends. Choose the stage you will board at.'
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                pickup_location = pickup_stage.name
            else:
                pickup_location = legacy_pickup_location

            if trip.status == 'boarding':
                _first_stage = (
                    PickupStage.objects
                    .filter(route_id=trip.route_id, is_active=True)
                    .order_by('order', 'id')
                    .first()
                )
                if (
                    pickup_stage is None
                    or _first_stage is None
                    or pickup_stage.id != _first_stage.id
                ):
                    return Response(
                        {
                            'error': (
                                'Boarding has started. Only the first '
                                'stage can be booked now. '
                                'Only the first stage can be booked.'
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # Cap unpaid bookings per user so one account cannot hold seats it
            # never pays for. The user row is locked so two simultaneous
            # requests cannot both slip under the cap.
            from django.contrib.auth import get_user_model
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            pending_cap = getattr(settings, 'MAX_PENDING_BOOKINGS_PER_USER', 3)
            if Booking.objects.filter(
                user=request.user, status='pending'
            ).filter(active_seat_q(now)).count() >= pending_cap:
                return Response(
                    {
                        'error': (
                            'You have too many unpaid bookings. Pay for or '
                            'cancel one before booking another.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Cap unpaid SEATS too: three bookings of a whole bus each would
            # otherwise let one account empty three trips without paying. Only
            # live holds count: a lapsed one has let its seats go.
            seat_cap = getattr(settings, 'MAX_PENDING_SEATS_PER_USER', 10)
            pending_seats = Booking.objects.filter(
                user=request.user, status='pending'
            ).filter(active_seat_q(now)).aggregate(n=Sum('seats'))['n'] or 0
            if pending_seats + seats > seat_cap:
                return Response(
                    {
                        'error': (
                            f'You can hold at most {seat_cap} unpaid seats at a time. '
                            f'You already hold {pending_seats}. Pay for or cancel '
                            'a booking first.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            held_here = Booking.objects.filter(
                user=request.user, trip=trip, status='pending',
            ).filter(active_seat_q(now)).aggregate(n=Sum('seats'))['n'] or 0
            if held_here + seats > settings.MAX_PENDING_SEATS_PER_TRIP:
                return _seat_limit(
                    'You already hold unpaid seats on this trip. Pay for them '
                    'or let them lapse before booking more '
                    f'(at most {settings.MAX_PENDING_SEATS_PER_TRIP} unpaid seats per trip).')

            try:
                reserve_seats(trip, seats, now)
            except NotEnoughSeats as exc:
                return Response(
                    {
                        'error': (
                            'Not enough seats available. '
                            f'Only {exc.available} remaining.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            total_amount = (
                trip.route.price * Decimal(str(seats))
            )
            if total_amount >= Decimal('100000000'):
                return Response(
                    {'error': 'This fare is too large to book online.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            tampered = _tampered_amount(request, total_amount)
            if tampered is not None:
                return tampered

            booking = Booking.objects.create(
                user=request.user,
                trip=trip,
                route=trip.route,
                driver=trip.driver,
                pickup_location=pickup_location,
                pickup_stage=pickup_stage,
                seats=seats,
                total_amount=total_amount,
                status='pending',
                held_until=hold_deadline(trip, now),
                idempotency_key=idempotency_key,
                idempotency_fingerprint=fingerprint if idempotency_key else '',
            )

            try:
                assign_seats(
                    trip, booking, validated_data.get('seat_numbers'), now
                )
            except SeatError as exc:
                transaction.set_rollback(True)
                return Response(
                    {'error': str(exc), 'code': 'seat_taken'},
                    status=status.HTTP_409_CONFLICT,
                )

        return Response(
            _booking_created_payload(booking),
            status=status.HTTP_201_CREATED
        )

    except Trip.DoesNotExist:
        return Response(
            {'error': 'Trip not found.'},
            status=status.HTTP_404_NOT_FOUND
        )


# ============================================================
# MY BOOKINGS & DETAILS
# ============================================================

def _bus_number(trip, driver):
    """The trip's own bus; trips made before buses were linked use the
    number typed on the driver."""
    if trip is not None and trip.bus_id:
        return trip.bus.bus_number
    return driver.bus_number if driver else None


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_bookings(request):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    # Do not depend on the scheduled jobs: a passenger must never see a
    # booking waiting for a payment that can no longer be accepted.
    cancel_dead_pending_bookings(Booking.objects.filter(user=request.user))

    bookings = (
        Booking.objects
        .filter(user=request.user)
        .select_related(
            'trip__route__company',
            'trip__driver',
            'trip__bus',
            'pickup_stage',
            'payment',
            'boarding_event',
        )
        .prefetch_related('seat_assignments')
        .order_by('-created_at')
    )

    data = []

    for b in bookings:
        trip = b.trip
        route = trip.route if trip else None
        driver = trip.driver if trip else None
        pickup_stage = b.pickup_stage

        data.append({
            'booking_id': b.id,
            'booking_number': b.booking_number,
            'verification_pin': (
                b.verification_pin
                if b.status == 'confirmed'
                or cash_due_on_board(b, getattr(b, 'payment', None))
                else None
            ),
            'pay_before': b.held_until if b.status == 'pending' else None,
            'boarded': hasattr(b, 'boarding_event'),
            'seat_numbers': sorted(a.seat_no for a in b.seat_assignments.all()),
            'trip_id': trip.id if trip else None,
            'departure_at': trip.departure_at if trip else None,
            'trip_status': trip.status if trip else None,
            # Free cancel / change of bus until this moment (see before_change_cutoff).
            'can_change': before_change_cutoff(trip),
            'change_cutoff_at': (
                trip.departure_at - timezone.timedelta(minutes=settings.BOOKING_CHANGE_CUTOFF_MINUTES)
                if trip else None
            ),

            'company_name': (
                route.company.name
                if route and route.company
                else None
            ),

            'route_name': route.name if route else None,
            'route_id': route.id if route else None,
            'company_id': route.company_id if route else None,
            'route_start_point': route.start_point if route else None,
            'route_end_point': route.end_point if route else None,

            'route_start_latitude': (
                float(route.start_latitude)
                if route and route.start_latitude is not None
                else None
            ),
            'route_start_longitude': (
                float(route.start_longitude)
                if route and route.start_longitude is not None
                else None
            ),
            'route_end_latitude': (
                float(route.end_latitude)
                if route and route.end_latitude is not None
                else None
            ),
            'route_end_longitude': (
                float(route.end_longitude)
                if route and route.end_longitude is not None
                else None
            ),
            'route_geometry': route.geometry if route else None,

            'pickup_location': b.pickup_location,
            'pickup_stage_id': (
                pickup_stage.id
                if pickup_stage
                else None
            ),
            'pickup_stage_name': (
                pickup_stage.name
                if pickup_stage
                else None
            ),
            'pickup_latitude': (
                float(pickup_stage.latitude)
                if pickup_stage
                else None
            ),
            'pickup_longitude': (
                float(pickup_stage.longitude)
                if pickup_stage
                else None
            ),

            'driver_id': driver.id if driver else None,
            'driver_name': driver.name if driver else None,
            'driver_bus_number': _bus_number(trip, driver),
            'bus_plate': trip.bus.registration_number if trip and trip.bus_id else None,
            'driver_latitude': (
                float(driver.latitude)
                if driver and driver.latitude is not None
                else None
            ),
            'driver_longitude': (
                float(driver.longitude)
                if driver and driver.longitude is not None
                else None
            ),

            'seats': b.seats,
            'total_amount': str(b.total_amount),
            'status': b.status,
            'payment_status': (
                b.payment.status
                if hasattr(b, 'payment')
                else 'unpaid'
            ),
            'payment_method': (
                b.payment.method
                if hasattr(b, 'payment')
                else None
            ),
            'created_at': b.created_at,
        })

    return Response(data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_all_bookings(request):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    company_id = request.query_params.get('company_id')
    if company_id and not str(company_id).isdigit():
        return Response(
            {'error': 'company_id must be a number.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Platform superuser can view bookings across all companies.
    if request.user.is_superuser:
        bookings = Booking.objects.all()

        if company_id:
            bookings = bookings.filter(
                route__company_id=company_id
            )

    # Company Manager, Auditor, and Operator can view only
    # bookings belonging to their assigned company.
    elif request.user.role in {
        'company_manager',
        'company_auditor',
        'company_operator',
    } and request.user.company_id:

        if (
            company_id
            and str(company_id) != str(request.user.company_id)
        ):
            return Response(
                {'error': 'You cannot view another company.'},
                status=status.HTTP_403_FORBIDDEN
            )

        bookings = Booking.objects.filter(
            route__company_id=request.user.company_id
        )

        # A route-restricted operator only sees their assigned routes.
        _scope = operator_route_ids(request.user)
        if _scope is not None:
            bookings = bookings.filter(route_id__in=_scope)

    else:
        return Response(
            {'error': 'Company staff authorization required'},
            status=status.HTTP_403_FORBIDDEN
        )

    bookings = bookings.select_related(
        'user',
        'route__company',
        'trip__driver',
        'payment'
    ).order_by('-created_at')

    data = [{
        'booking_id': b.id,
        'booking_number': b.booking_number,
        'user': b.user.display_name,
        'user_phone': b.user.phone_number,
        'company_id': b.route.company_id,
        'company_name': b.route.company.name,
        'trip_id': b.trip.id if b.trip else None,
        'driver_id': b.driver_id,
        'driver_name': b.driver.name if b.driver else None,
        'route_name': b.route.name,
        'pickup_location': b.pickup_location,
        'seats': b.seats,
        'total_amount': str(b.total_amount),
        'status': b.status,
        'payment_status': (
            b.payment.status
            if hasattr(b, 'payment')
            else 'unpaid'
        ),
        'payment_method': (
            b.payment.method
            if hasattr(b, 'payment')
            else None
        ),
        'created_at': b.created_at,
    } for b in bookings]

    return Response(
        data,
        status=status.HTTP_200_OK
    )


def _not_yours(user, booking):
    """
    Refusal for a booking the caller may not use. Its owner and staff of its
    own company already know it exists, so they get 403. Anyone else gets the same
    404 as a missing id, so booking ids cannot be enumerated.
    """
    if booking.user_id == user.id or (
        user.role in {'company_manager', 'company_auditor', 'company_operator'}
        and user.company_id == booking.route.company_id
    ):
        return Response(
            {'error': 'Unauthorized'},
            status=status.HTTP_403_FORBIDDEN
        )
    return Response(
        {'error': 'Booking not found'},
        status=status.HTTP_404_NOT_FOUND
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_booking_detail(request, booking_id):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    try:
        booking = (
            Booking.objects
            .select_related(
                'user',
                'trip__route',
                'payment'
            )
            .get(id=booking_id)
        )
    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    user = request.user

    is_company_staff = (
        user.role in {
            'company_manager',
            'company_auditor',
            'company_operator',
        }
        and user.company_id == booking.route.company_id
        and can_handle_route(user, booking.route_id)
    )

    if (
        booking.user != user
        and not user.is_superuser
        and not is_company_staff
    ):
        return _not_yours(user, booking)

    data = {
        'booking_id': booking.id,
        'booking_number': booking.booking_number,
        'user': booking.user.display_name,
        'trip_id': booking.trip.id if booking.trip else None,
        'route_name': booking.route.name,
        'pickup_location': booking.pickup_location,
        'seats': booking.seats,
        'total_amount': str(booking.total_amount),
        'status': booking.status,
        'pay_before': booking.held_until if booking.status == 'pending' else None,
        'payment_status': (
            booking.payment.status
            if hasattr(booking, 'payment')
            else 'unpaid'
        ),
        'payment_method': (
            booking.payment.method
            if hasattr(booking, 'payment')
            else None
        ),
        'created_at': booking.created_at,
    }

    return Response(data, status=status.HTTP_200_OK)


# ============================================================
# ASSIGN DRIVER & CANCEL BOOKING
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def assign_driver(request, booking_id):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    try:
        booking = (
            Booking.objects
            .select_related('route__company')
            .get(id=booking_id)
        )
    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    user = request.user

    is_allowed = (
        user.is_superuser
        or (
            user.role in {
                'company_manager',
                'company_operator',
            }
            and user.company_id == booking.route.company_id
            # A route-restricted operator may only act on their assigned
            # routes (matches verify_boarding / cash / walk-in / trips).
            and can_handle_route(user, booking.route_id)
        )
    )

    if not is_allowed:
        return Response(
            {'error': 'Manager or Operator authorization required'},
            status=status.HTTP_403_FORBIDDEN
        )

    serializer = AssignDriverSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    if booking.trip_id is None:
        return Response(
            {'error': 'This booking is not linked to a trip.'},
            status=status.HTTP_409_CONFLICT
        )

    if booking.status in {'completed', 'cancelled', 'no_show'}:
        return Response(
            {
                'error': (
                    f'Cannot assign a driver to a booking with '
                    f'status: {booking.status}'
                )
            },
            status=status.HTTP_409_CONFLICT
        )

    driver_id = serializer.validated_data['driver_id']

    with transaction.atomic():
        trip = (
            Trip.objects
            .select_for_update()
            .get(id=booking.trip_id)
        )

        try:
            driver = (
                Driver.objects
                .select_for_update()
                .get(id=driver_id)
            )
        except Driver.DoesNotExist:
            return Response(
                {'error': 'Driver not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        if driver.company_id != booking.route.company_id:
            return Response(
                {
                    'error': (
                        'Driver must belong to the same company '
                        'as the booking.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # An existing assignment may remain in place even after
        # the driver has been deactivated. A NEW assignment may not.
        if (
            trip.driver_id != driver.id
            and not driver.is_available
        ):
            return Response(
                {
                    'error': (
                        'This driver is unavailable and cannot be '
                        'assigned to a new trip.'
                    )
                },
                status=status.HTTP_409_CONFLICT
            )

        # Once boarding starts, changing the trip driver would make
        # the historical driver assignment ambiguous.
        if trip.status != 'scheduled':
            if trip.driver_id == driver.id:
                return Response(
                    {
                        'message': 'This driver is already assigned.',
                        'booking_id': booking.id,
                    },
                    status=status.HTTP_200_OK,
                )

            return Response(
                {
                    'error': (
                        'The trip driver can only be changed while '
                        'the trip is still scheduled.'
                    )
                },
                status=status.HTTP_409_CONFLICT
            )

        conflicting_trip = (
            Trip.objects
            .filter(
                driver=driver,
                departure_at=trip.departure_at,
                status__in={
                    'scheduled',
                    'boarding',
                    'departed',
                },
            )
            .exclude(id=trip.id)
            .exists()
        )

        if conflicting_trip:
            return Response(
                {
                    'error': (
                        'This driver is already assigned to another '
                        'active trip at the same departure time.'
                    )
                },
                status=status.HTTP_409_CONFLICT
            )

        trip.driver = driver
        trip.save(update_fields=['driver'])

        # Keep active bookings aligned with the trip's new driver.
        # Completed historical bookings are deliberately untouched.
        (
            Booking.objects
            .filter(trip=trip)
            .exclude(status__in={'completed', 'cancelled', 'no_show'})
            .update(driver=driver)
        )

    return Response(
        {
            'message': 'Driver assigned successfully.',
            'booking_id': booking.id
        },
        status=status.HTTP_200_OK
    )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def move_booking_to_trip(request, booking_id):
    """
    Dispatcher action: move one active booking onto another bus of the
    same route (for example when a bus is full). The target must be
    scheduled or boarding and have enough free seats.
    """
    user = request.user

    try:
        booking = (
            Booking.objects
            .select_related('route__company')
            .get(id=booking_id)
        )
    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    is_staff_move = (
        user.is_superuser
        or (
            user.role in {'company_manager', 'company_operator'}
            and user.company_id == booking.route.company_id
            and can_handle_route(user, booking.route_id)
        )
    )
    is_own_move = booking.user_id == user.id
    if not (is_staff_move or is_own_move):
        return Response(
            {'error': 'Manager or Operator authorization required'},
            status=status.HTTP_403_FORBIDDEN
        )

    target_id = parse_id(request.data.get('trip_id'))
    if target_id is None:
        return Response(
            {'error': 'trip_id is required.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if booking.trip_id is None:
        return Response(
            {'error': 'This booking is not linked to a trip.'},
            status=status.HTTP_409_CONFLICT
        )

    if booking.status in {'completed', 'cancelled', 'no_show'}:
        return Response(
            {'error': f'Cannot move a booking with status: {booking.status}'},
            status=status.HTTP_409_CONFLICT
        )

    if booking.trip_id == target_id:
        return Response(
            {'error': 'The booking is already on this trip.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    with transaction.atomic():
        locked = {
            tr.id: tr
            for tr in Trip.objects.select_for_update().filter(
                id__in=[booking.trip_id, target_id]
            ).order_by('id')
        }
        old_trip = locked.get(booking.trip_id)
        new_trip = locked.get(target_id)

        # Re-read the booking under lock: a cancel may have landed since the
        # unlocked read above.
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.status in {'completed', 'cancelled', 'no_show'}:
            return Response(
                {'error': f'Cannot move a booking with status: {booking.status}'},
                status=status.HTTP_409_CONFLICT
            )

        # The unlocked read picked which trips to lock; if the booking moved
        # meanwhile, the old trip held here is the wrong one.
        if old_trip is None or booking.trip_id != old_trip.id:
            return Response(
                {'error': 'The booking changed trips. Please try again.'},
                status=status.HTTP_409_CONFLICT
            )

        if new_trip is None:
            return Response(
                {'error': 'Target trip not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

        if new_trip.route_id != booking.route_id:
            return Response(
                {'error': 'The target trip must be on the same route.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if old_trip.status not in ('scheduled', 'boarding'):
            return Response(
                {'error': 'The current trip has already left.'},
                status=status.HTTP_409_CONFLICT
            )
        if not is_staff_move and not before_change_cutoff(old_trip):
            return Response(
                {
                    'error': (
                        'Your bus leaves in less than '
                        f'{settings.BOOKING_CHANGE_CUTOFF_MINUTES} minutes, so '
                        'the booking can no longer be moved to another trip.'
                    ),
                    'code': 'change_cutoff',
                },
                status=status.HTTP_409_CONFLICT
            )

        now = timezone.now()
        if new_trip.status not in ('scheduled', 'boarding') or trip_has_departed(new_trip):
            return Response(
                {'error': 'The target trip is not open for passengers.'},
                status=status.HTTP_409_CONFLICT
            )
        if not is_staff_move and not before_change_cutoff(new_trip):
            return Response(
                {'error': 'That bus leaves too soon to move onto. Pick a later one.',
                 'code': 'change_cutoff'},
                status=status.HTTP_409_CONFLICT
            )

        # Staff moves are exempt from the booking cut-off: the stage organises
        # seats inside it, and only passenger-initiated bookings are closed.
        if not is_staff_move and now >= booking_closes_at(new_trip):
            return Response(
                {'error': 'Booking is closed for that trip. Pick a later one.',
                 'code': 'booking_closed'},
                status=status.HTTP_409_CONFLICT
            )
        available_seats = new_trip.capacity - seats_taken(
            new_trip, now, exclude_booking_id=booking.pk)
        if booking.seats > available_seats:
            return Response(
                {
                    'error': 'The target trip does not have enough free seats.',
                    'available_seats': available_seats,
                    'requested_seats': booking.seats,
                },
                status=status.HTTP_409_CONFLICT
            )

        booking.trip = new_trip
        booking.driver = new_trip.driver
        update_fields = ['trip', 'driver', 'updated_at']
        if booking.status == 'pending' and booking.held_until is not None:
            # A hold never outlives the departure of the trip it is on.
            booking.held_until = min(booking.held_until, new_trip.departure_at)
            update_fields.append('held_until')
        booking.save(update_fields=update_fields)
        move_seats(old_trip, new_trip, booking)

    import logging
    logging.getLogger(__name__).info(
        'booking %s moved from trip %s to trip %s by user %s',
        booking.id, old_trip.id, new_trip.id, user.pk,
    )

    return Response(
        {
            'message': 'Booking moved.',
            'booking_id': booking.id,
            'from_trip': old_trip.id,
            'to_trip': new_trip.id,
            'driver_id': new_trip.driver_id,
        },
        status=status.HTTP_200_OK
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_booking(request, booking_id):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    user = request.user

    try:
        with transaction.atomic():
            # Lock Trip first, then Booking.
            # This matches verify_boarding() and serializes
            # cancellation against trip status changes/boarding.
            #
            # Booking.trip is nullable, so obtain trip_id first
            # without select_for_update(), then lock the Trip
            # separately before locking the Booking.
            booking_ref = (
                Booking.objects
                .only("trip_id")
                .get(id=booking_id)
            )

            trip = None

            if booking_ref.trip_id is not None:
                trip = (
                    Trip.objects
                    .select_for_update()
                    .get(pk=booking_ref.trip_id)
                )

            booking = (
                Booking.objects
                .select_for_update()
                .get(id=booking_id)
            )

            # The booking must still point at the Trip we locked.
            # A concurrent reassignment/reschedule must not let us
            # make a decision using a stale Trip row.
            if (
                trip is not None
                and booking.trip_id != trip.id
            ):
                return Response(
                    {
                        "error": (
                            "This booking changed trips. "
                            "Please refresh and try again."
                        )
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            if (
                booking.user != user
                and not (
                    user.is_superuser
                    or (
                        user.role in {
                            'company_manager',
                            'company_operator',
                        }
                        and user.company_id == booking.route.company_id
                        and can_handle_route(user, booking.route_id)
                    )
                )
            ):
                return _not_yours(user, booking)

            if booking.status in (
                'cancelled',
                'completed',
                'no_show',
            ):
                return Response(
                    {
                        'error': (
                            'Cannot cancel a booking with '
                            f'status: {booking.status}'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            fault_party = request.data.get(
                'fault_party',
                'passenger'
            )

            if fault_party not in (
                'passenger',
                'company',
            ):
                return Response(
                    {
                        'error': (
                            'Invalid fault_party parameter. '
                            'Must be "passenger" or "company".'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # A passenger may not cancel once boarding begins.
            # Company-fault cancellation is still permitted while
            # the trip is boarding so operators can resolve a real
            # operational incident.
            if trip is not None:
                if trip.status in {'departed', 'completed'}:
                    return Response(
                        {
                            'error': (
                                'This trip has already departed. '
                                'The booking can no longer be cancelled.'
                            )
                        },
                        status=status.HTTP_409_CONFLICT
                    )

                if (
                    trip.status == 'boarding'
                    and fault_party == 'passenger'
                ):
                    return Response(
                        {
                            'error': (
                                'Passenger cancellation is no longer '
                                'allowed once boarding has started.'
                            )
                        },
                        status=status.HTTP_409_CONFLICT
                    )

                if trip_has_departed(trip):
                    return Response(
                        {
                            'error': (
                                'This trip has already departed. '
                                'The booking can no longer be cancelled.'
                            )
                        },
                        status=status.HTTP_409_CONFLICT
                    )

            if fault_party == 'company' and not (
                user.is_superuser
                or (
                    user.role in {
                        'company_manager',
                        'company_operator',
                    }
                    and user.company_id == booking.route.company_id
                    and can_handle_route(user, booking.route_id)
                )
            ):
                return Response(
                    {
                        'error': (
                            'Only staff can cancel with '
                            'company fault status.'
                        )
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

            from .services import (
                RefundRejected,
                claim_booking_refund,
                execute_booking_refund,
                release_refund_claim,
            )

            previous_status = booking.status
            refund_party = fault_party
            if fault_party == 'passenger' and before_change_cutoff(trip):
                refund_party = 'passenger_early'
            # Reserve the refund inside this transaction but do NOT call
            # Paystack here: a rollback after Paystack accepted the refund
            # would erase the reservation and allow a second refund.
            refund_amount, refund_claim = claim_booking_refund(
                booking,
                refund_party
            )

            booking.status = 'cancelled'
            booking.save(update_fields=['status'])

    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    except ValueError as exc:
        return Response(
            {'error': str(exc)},
            status=status.HTTP_409_CONFLICT
        )

    refund_state = None

    if refund_claim is not None:
        # The locks are released and the reservation is committed, so it is
        # now safe to talk to Paystack.
        try:
            refund_amount = execute_booking_refund(refund_claim)
        except RefundRejected as exc:
            # Paystack definitely refunded nothing: undo the cancellation
            # and free the reservation so a retry starts clean.
            release_refund_claim(refund_claim)
            seat_lost = False
            with transaction.atomic():
                # Same lock order as the cancel above: trip, then booking.
                # The seat may have been resold or the trip may have left
                # while Paystack was being called.
                locked_trip = (
                    Trip.objects.select_for_update(of=('self',))
                    .filter(pk=booking_ref.trip_id).first()
                    if booking_ref.trip_id else None
                )
                restored = (
                    Booking.objects
                    .select_for_update()
                    .get(pk=booking_id)
                )
                if restored.status == 'cancelled':
                    # seats_taken counts blocked seats too; the cancelled
                    # booking itself is excluded from it.
                    seat_free = locked_trip is None or (
                        not trip_has_departed(locked_trip)
                        and seats_taken(locked_trip) + restored.seats
                        <= locked_trip.capacity
                    )
                    if seat_free:
                        old_numbers = list(
                            restored.seat_assignments.values_list('seat_no', flat=True)
                        )
                        restored.status = previous_status
                        restored.status = previous_status
                        update_fields = ['status']
                        if previous_status == 'pending':
                            # A pending booking only holds its seat until
                            # held_until, so give it a fresh hold.
                            restored.held_until = hold_deadline(locked_trip)
                            update_fields.append('held_until')
                        restored.save(update_fields=update_fields)
                        if locked_trip is not None:
                            # Its seat may have been resold meanwhile: keep
                            # the old numbers if still free, else the lowest free.
                            try:
                                assign_seats(locked_trip, restored, old_numbers or None)
                            except SeatError:
                                assign_seats(locked_trip, restored)
                    else:
                        seat_lost = True
                        # The passenger is owed the refund: the
                        # process_noshows sweep keeps retrying it.
                        Payment.objects.filter(pk=refund_claim.payment_id).update(
                            refund_reason=f'seat_lost_{refund_party.replace("passenger_", "")}')
            if seat_lost:
                _alert_payment_problem(
                    refund_claim.provider_reference,
                    f'refund for booking {refund_claim.booking_number} was '
                    f'rejected and its seat is gone; refund it manually',
                )
                return Response(
                    {
                        'error': (
                            f'{exc} The booking stays cancelled and our '
                            'team has been alerted to refund you.'
                        )
                    },
                    status=status.HTTP_409_CONFLICT
                )
            return Response(
                {'error': str(exc)},
                status=status.HTTP_409_CONFLICT
            )
        except ValueError:
            # Outcome unknown (timeout or unreadable reply). The booking
            # stays cancelled and the refund stays "processing" until it is
            # reconciled; it is never sent a second time automatically.
            refund_state = 'processing'
            _alert_payment_problem(
                refund_claim.provider_reference,
                f'refund for booking {refund_claim.booking_number} is '
                f'unconfirmed; check Paystack before retrying',
            )

    response_body = {
        'message': 'Booking cancelled successfully.',
        'fault_party': fault_party,
        'free_cancellation': refund_party == 'passenger_early',
        'refund_amount': str(refund_amount),
    }

    if refund_state:
        response_body['refund_status'] = refund_state
        response_body['message'] = (
            'Booking cancelled. Your refund is being confirmed '
            'with the payment provider.'
        )

    return Response(response_body, status=status.HTTP_200_OK)


def _resolve_incident_inner(request, booking_id, deferred):
    """
    Let an incident-affected passenger choose refund or reschedule.

    Rescheduling keeps the existing booking and payment. It does not
    create a second payment or a second booking.
    """
    from .services import claim_booking_refund

    resolution = request.data.get('resolution')

    if resolution not in ('refund', 'reschedule'):
        return Response(
            {
                'error': (
                    'Invalid resolution. '
                    'Choose "refund" or "reschedule".'
                )
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with transaction.atomic():
            # Trips first (ordered by id), then the Booking: the order
            # move_booking_to_trip uses, so the two cannot deadlock. The
            # booking's own trip is locked too because either choice frees
            # its seat.
            trip_ids = {
                tid for tid in Booking.objects
                .filter(pk=booking_id).values_list('trip_id', flat=True)
                if tid is not None
            }
            requested_trip_id = parse_id(request.data.get('replacement_trip_id'))
            if resolution == 'reschedule' and requested_trip_id:
                trip_ids.add(requested_trip_id)
            list(
                Trip.objects.select_for_update(of=('self',))
                .filter(pk__in=trip_ids).order_by('pk')
            )

            booking = (
                Booking.objects
                .select_for_update()
                .get(id=booking_id)
            )

            booking = (
                Booking.objects
                .select_related('route', 'trip', 'user')
                .get(id=booking.id)
            )

            if booking.trip_id is not None and booking.trip_id not in trip_ids:
                return Response(
                    {'error': 'This booking changed trips. Please try again.'},
                    status=status.HTTP_409_CONFLICT
                )

            if booking.user_id != request.user.id:
                return Response(
                    {
                        'error': (
                            'Only the passenger who owns this '
                            'booking can resolve the incident.'
                        )
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

            if booking.trip_id is None:
                return Response(
                    {
                        'error': 'This booking is not linked to a trip.'
                    },
                    status=status.HTTP_409_CONFLICT
                )

            if booking.status in (
                'cancelled',
                'completed',
                'no_show',
            ):
                return Response(
                    {
                        'error': (
                            'This booking cannot be resolved because '
                            f'its status is "{booking.status}".'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            incident = (
                booking.trip.incidents
                .filter(
                    status__in=('reported', 'investigating')
                )
                .order_by('-reported_at')
                .first()
            )

            if incident is None:
                return Response(
                    {
                        'error': (
                            'No active incident was found for '
                            'this booking.'
                        )
                    },
                    status=status.HTTP_409_CONFLICT
                )

            existing = (
                IncidentResolution.objects
                .select_for_update()
                .filter(booking=booking)
                .first()
            )

            if existing is not None:
                return Response(
                    {
                        'error': (
                            'This booking already has an incident '
                            'resolution.'
                        ),
                        'resolution': existing.resolution,
                        'status': existing.status,
                    },
                    status=status.HTTP_409_CONFLICT
                )

            if resolution == 'refund':
                previous_status = booking.status

                # Reserve the refund in the database only. The wrapper view
                # calls Paystack after this transaction has committed.
                refund_amount, refund_claim = claim_booking_refund(
                    booking,
                    'company',
                )

                booking.status = 'cancelled'
                booking.save(update_fields=['status'])

                incident_resolution = IncidentResolution.objects.create(
                    booking=booking,
                    incident=incident,
                    resolution='refund',
                    status='completed',
                    refund_amount=refund_amount,
                    completed_at=timezone.now(),
                )

                if refund_claim is not None:
                    deferred.append(
                        (
                            refund_claim,
                            booking.pk,
                            previous_status,
                            incident_resolution.pk,
                        )
                    )

                return Response(
                    {
                        'message': 'Incident refund requested successfully.',
                        'resolution': 'refund',
                        'refund_amount': str(refund_amount),
                        'booking_status': booking.status,
                    },
                    status=status.HTTP_200_OK
                )

            replacement_trip_id = request.data.get(
                'replacement_trip_id'
            )

            if not replacement_trip_id:
                return Response(
                    {
                        'error': (
                            'replacement_trip_id is required '
                            'for rescheduling.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            replacement_trip_id = parse_id(replacement_trip_id)
            if replacement_trip_id is None:
                return Response(
                    {'error': 'replacement_trip_id must be a valid id.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                # Already locked at the top of this transaction.
                replacement_trip = (
                    Trip.objects
                    .select_related('route', 'driver')
                    .get(id=replacement_trip_id)
                )
            except Trip.DoesNotExist:
                return Response(
                    {'error': 'Replacement trip not found.'},
                    status=status.HTTP_404_NOT_FOUND
                )

            if replacement_trip.id == booking.trip_id:
                return Response(
                    {
                        'error': (
                            'The replacement trip must be different '
                            'from the affected trip.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if replacement_trip.route_id != booking.route_id:
                return Response(
                    {
                        'error': (
                            'The replacement trip must use the '
                            'same route as the original booking.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if replacement_trip.status != 'scheduled':
                return Response(
                    {
                        'error': (
                            'The replacement trip is not available '
                            'for booking.'
                        )
                    },
                    status=status.HTTP_409_CONFLICT
                )

            # Deliberately no booking cut-off check here: the passenger is
            # being moved because of the incident, so only a trip that has
            # already left is refused.
            if replacement_trip.departure_at <= timezone.now():
                return Response(
                    {
                        'error': (
                            'The replacement trip has already '
                            'departed.'
                        )
                    },
                    status=status.HTTP_409_CONFLICT
                )

            available_seats = (
                replacement_trip.capacity - seats_taken(replacement_trip)
            )

            if booking.seats > available_seats:
                return Response(
                    {
                        'error': (
                            'The replacement trip does not have '
                            'enough available seats.'
                        ),
                        'available_seats': available_seats,
                        'requested_seats': booking.seats,
                    },
                    status=status.HTTP_409_CONFLICT
                )

            if not Payment.objects.filter(
                booking=booking, status='confirmed'
            ).exists():
                return Response(
                    {'error': 'Only a paid booking can be rescheduled.'},
                    status=status.HTTP_409_CONFLICT
                )

            old_trip = booking.trip

            booking.trip = replacement_trip
            booking.driver = replacement_trip.driver
            booking.status = 'confirmed'
            booking.save(
                update_fields=[
                    'trip',
                    'driver',
                    'status',
                    'updated_at',
                ]
            )
            move_seats(old_trip, replacement_trip, booking)

            IncidentResolution.objects.create(
                booking=booking,
                incident=incident,
                resolution='reschedule',
                replacement_trip=replacement_trip,
                status='completed',
                completed_at=timezone.now(),
            )

            return Response(
                {
                    'message': (
                        'Booking rescheduled successfully. '
                        'No additional payment was required.'
                    ),
                    'resolution': 'reschedule',
                    'booking_id': booking.id,
                    'booking_number': booking.booking_number,
                    'previous_trip_id': old_trip.id,
                    'replacement_trip_id': replacement_trip.id,
                    'payment_unchanged': True,
                    'booking_status': booking.status,
                },
                status=status.HTTP_200_OK
            )

    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found.'},
            status=status.HTTP_404_NOT_FOUND
        )

    except ValueError as exc:
        return Response(
            {'error': str(exc)},
            status=status.HTTP_409_CONFLICT
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resolve_incident_booking(request, booking_id):
    """
    Incident resolution. The database work (and the refund reservation)
    commits inside _resolve_incident_inner; Paystack is called here, after.
    """
    from .services import (
        RefundRejected,
        execute_booking_refund,
        release_refund_claim,
    )

    deferred = []
    response = _resolve_incident_inner(request, booking_id, deferred)

    if not deferred:
        return response

    claim, booking_pk, previous_status, resolution_pk = deferred[0]

    try:
        execute_booking_refund(claim)
    except RefundRejected as exc:
        # Paystack definitely refunded nothing: undo the cancellation and
        # the resolution so the passenger can choose again.
        release_refund_claim(claim)
        seat_lost = False
        with transaction.atomic():
            # Trip first, then Booking (the cancel lock order). The seat may
            # have been resold while Paystack was being called. No departure
            # check: an incident can happen after the bus has left.
            try:
                locked_trip, restored = lock_trip_then_booking(booking_pk)
            except BookingMoved:
                locked_trip, restored = lock_trip_then_booking(booking_pk)
            if restored.status == 'cancelled':
                seat_free = locked_trip is None or (
                    seats_taken(locked_trip) + restored.seats
                    <= locked_trip.capacity
                )
                if seat_free:
                    old_numbers = list(
                        restored.seat_assignments.values_list('seat_no', flat=True)
                    )
                    restored.status = previous_status
                    update_fields = ['status']
                    if previous_status == 'pending':
                        # A pending booking only holds its seat until held_until.
                        restored.held_until = hold_deadline(locked_trip)
                        update_fields.append('held_until')
                    restored.save(update_fields=update_fields)
                    if locked_trip is not None:
                        try:
                            assign_seats(locked_trip, restored, old_numbers or None)
                        except SeatError:
                            assign_seats(locked_trip, restored)
                    IncidentResolution.objects.filter(pk=resolution_pk).delete()
                else:
                    seat_lost = True
                    IncidentResolution.objects.filter(
                        pk=resolution_pk).update(status='failed')
            else:
                IncidentResolution.objects.filter(pk=resolution_pk).delete()
        if seat_lost:
            _alert_payment_problem(
                claim.provider_reference,
                f'incident refund for booking {claim.booking_number} was '
                f'rejected and its seat is gone; refund it manually',
            )
            return Response(
                {
                    'error': (
                        f'{exc} The booking stays cancelled and our '
                        'team has been alerted to refund you.'
                    )
                },
                status=status.HTTP_409_CONFLICT
            )
        return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)
    except ValueError:
        # Outcome unknown: stays "processing" until reconciled, never resent.
        response.data['refund_status'] = 'processing'
        response.data['message'] = (
            'Booking cancelled. Your refund is being confirmed '
            'with the payment provider.'
        )
        _alert_payment_problem(
            claim.provider_reference,
            f'incident refund for booking {claim.booking_number} is '
            f'unconfirmed; check Paystack before retrying',
        )

    return response


# ============================================================
# VERIFY BOARDING & SETTLEMENT RELEASE
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([BoardingVerifyThrottle])
def verify_boarding(request, booking_id):
    boarding_pin = request.data.get('boarding_pin')
    qr_data = request.data.get('qr_data')

    if not boarding_pin and not qr_data:
        return Response(
            {
                'error': (
                    'Either QR data or boarding PIN is required.'
                )
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    user = request.user

    try:
        with transaction.atomic():
            # Lock the Trip first, then the Booking.
            # This keeps the lock order consistent with trip-ending
            # operations and prevents state races around payment release.
            booking_ref = (
                Booking.objects
                .only("trip_id")
                .get(id=booking_id)
            )

            if booking_ref.trip_id is None:
                return Response(
                    {
                        "error": (
                            "This booking is not attached to an active trip."
                        )
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            trip = (
                Trip.objects
                .select_for_update(of=('self',))
                .select_related("driver")
                .get(id=booking_ref.trip_id)
            )

            booking = (
                Booking.objects
                .select_for_update()
                .get(id=booking_id)
            )

            if booking.trip_id != trip.id:
                return Response(
                    {
                        "error": (
                            "This booking changed trips. Please refresh "
                            "and try again."
                        )
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            # Boarding verification is allowed for:
            # - Django superusers
            # - Company Managers for their own company
            # - Company Operators for their own company
            # - The driver assigned to this trip
            #
            # Company Auditors are read-only.
            # Generic is_staff=True does not grant boarding authority.
            is_authorized = (
                user.is_superuser
                or (
                    user.role in {
                        'company_manager',
                        'company_operator',
                    }
                    and user.company_id == booking.route.company_id
                    and can_handle_route(user, booking.route_id)
                )
            )

            if not is_authorized and is_driver_account_for(user, trip.driver):
                is_authorized = True

            if not is_authorized:
                return _not_yours(user, booking)

            payment = (
                Payment.objects.select_for_update()
                .filter(booking=booking).first()
            )
            # Cash on board: the passenger hands over the fare and the driver
            # checks their PIN. That PIN check is the cash receipt; there is
            # no separate "confirm cash" step.
            pays_cash_now = (
                cash_due_on_board(booking, payment)
                and cash_still_payable(trip)
            )

            # Taking cash follows the same rule as confirm_cash_payment:
            # operators only when OPERATORS_CAN_CONFIRM_CASH is on.
            if (
                pays_cash_now
                and not user.is_superuser
                and user.role == 'company_operator'
                and not getattr(settings, 'OPERATORS_CAN_CONFIRM_CASH', False)
            ):
                return Response(
                    {'error': 'Operators cannot take cash payments.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if booking.status != 'confirmed' and not pays_cash_now:
                return Response(
                    {
                        'error': (
                            'Cannot board booking with status: '
                            f'{booking.status}'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if payment is None:
                return Response(
                    {
                        'error': (
                            'No payment record for this booking.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if payment.status != 'confirmed' and not pays_cash_now:
                return Response(
                    {
                        'error': (
                            'Payment is not confirmed. '
                            'Cannot board.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # -------------------------------------------------
            # QR VERIFICATION
            # -------------------------------------------------

            if qr_data:
                # The QR carries "<booking_number>:<pin>". The booking number
                # alone is visible to drivers and staff, so it proves nothing.
                # Wrong scans share the PIN failure counter, so QR is not a
                # way around the 5-tries limit.
                import hmac
                from django.core.cache import cache
                fail_key = f'pin-fail:{booking.id}'
                if cache.get(fail_key, 0) >= 5:
                    return Response(
                        {'error': 'Too many wrong attempts. Wait 15 minutes.'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS
                    )
                expected = f'{booking.booking_number}:{booking.verification_pin}'
                if not hmac.compare_digest(
                    str(qr_data).strip().encode('utf-8'),
                    expected.encode('utf-8'),
                ):
                    cache.add(fail_key, 0, 900)
                    cache.incr(fail_key)
                    return Response(
                        {'error': 'Invalid QR data.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                verification_method = 'qr'
                is_override = False

            # -------------------------------------------------
            # PIN FALLBACK
            # -------------------------------------------------

            elif boarding_pin:
                from django.core.cache import cache
                import hmac
                fail_key = f'pin-fail:{booking.id}'
                if cache.get(fail_key, 0) >= 5:
                    return Response(
                        {'error': 'Too many wrong PINs. Scan the QR code or wait 15 minutes.'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS
                    )
                if not hmac.compare_digest(
                    str(getattr(booking, 'verification_pin', '')).encode('utf-8'),
                    str(boarding_pin).encode('utf-8'),
                ):
                    cache.add(fail_key, 0, 900)
                    cache.incr(fail_key)
                    return Response(
                        {
                            'error': (
                                'Invalid boarding PIN override.'
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                verification_method = 'pin'
                is_override = True

            else:
                return Response(
                    {
                        'error': (
                            'Invalid verification payload.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Boarding/payment release is only valid once the trip
            # has actually started boarding or is already departed.
            if trip.status not in {"boarding", "departed"}:
                return Response(
                    {
                        "error": (
                            "Boarding verification is available only "
                            "when the trip is boarding or departed."
                        ),
                        "trip_status": trip.status,
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            # A booking can only be boarded once.
            if BoardingEvent.objects.filter(
                booking=booking
            ).exists():
                return Response(
                    {
                        'error': (
                            'Passenger has already been '
                            'checked in.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if pays_cash_now:
                # Same rule as confirm_cash_payment: a lapsed hold whose seats
                # were resold cannot board, and one still free gets numbers back.
                if hold_expired_and_seat_gone(booking, trip):
                    return Response(
                        {
                            'error': (
                                'The time to hold this booking has run out '
                                'and its seats are taken. Board a walk-up '
                                'passenger instead.'
                            ),
                            'code': 'hold_expired',
                        },
                        status=status.HTTP_409_CONFLICT,
                    )
                ensure_numbers(trip, booking)

            # Record the real-world boarding event.
            BoardingEvent.objects.create(
                booking=booking,
                trip=booking.trip,
                method=verification_method,
                verified_by=request.user
            )

            # Release the internal financial hold when boarding
            # has been successfully verified.
            #
            # Cash payments may not have a BookingHold, so only
            # release a hold when one exists.
            if hasattr(booking, 'financial_hold'):
                release_booking_hold(booking)

            # Boarding makes the payment eligible for settlement.
            # It does NOT transfer money between Django wallets.
            payment.settlement_status = 'eligible'
            update_fields = ['settlement_status']
            if pays_cash_now:
                payment.status = 'confirmed'
                payment.confirmed_at = timezone.now()
                update_fields += ['status', 'confirmed_at']
            payment.save(update_fields=update_fields)

            # Mark the booking as completed.
            booking.status = 'completed'
            booking.save(update_fields=['status'])

            # Record successful boarding for integrity/reliability
            # calculations.
            from django.db.models import F as _F
            type(booking.user).objects.filter(pk=booking.user_id).update(
                boarded_count=_F('boarded_count') + 1
            )

            return Response(
                {
                    'message': (
                        'Boarding verified successfully. '
                        'Payment is now eligible for settlement.'
                    ),
                    'settlement_status': (
                        payment.settlement_status
                    ),
                    'verification_method': (
                        verification_method
                    ),
                    'override_used': is_override,
                    'booking_id': booking.id,
                    'cash_collected': (
                        str(payment.amount) if pays_cash_now else None
                    ),
                },
                status=status.HTTP_200_OK
            )

    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found.'},
            status=status.HTTP_404_NOT_FOUND
        )


# ============================================================
# LOCATION & DRIVER BOOKINGS
# ============================================================


def _passenger_can_track(booking):
    """
    Confirmed, or on board with the trip still running. Boarding marks a
    booking 'completed' for settlement, but the passenger is still riding.
    """
    if booking.status == 'confirmed':
        return True
    # Paying cash on boarding: they need to see the bus to meet it.
    if cash_due_on_board(booking, getattr(booking, 'payment', None)):
        return True
    return (
        booking.status == 'completed'
        and hasattr(booking, 'boarding_event')
        and booking.trip is not None
        and booking.trip.status in ('boarding', 'departed')
    )



def _route_traffic_payload(route, own_driver_id):
    """Traffic is a nice-to-have: never let it break live tracking."""
    if route is None:
        return []
    try:
        from drivers.traffic import route_traffic
        return route_traffic(route, own_driver_id)
    except Exception:
        logging.getLogger(__name__).exception('route traffic failed for route %s', route.id)
        return []


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def booking_live_location(request, booking_id):
    """
    Return the latest passenger and assigned-driver coordinates
    for a booking.

    Access:
    - Passenger who owns the booking
    - Driver assigned to the booking
    - Company staff belonging to the booking's company
    - Platform/superuser
    """
    from .live_signals import location_freshness_for_booking
    booking = (
        Booking.objects
        .select_related(
            'user',
            'route',
            'driver',
            'trip',
        )
        .filter(id=booking_id)
        .first()
    )

    if not booking:
        return Response(
            {'error': 'Booking not found'},
            status=status.HTTP_404_NOT_FOUND,
        )

    user = request.user

    is_passenger = booking.user_id == user.id

    is_assigned_driver = (
        booking.driver_id is not None
        and user.role == 'driver'
        and is_driver_account_for(user, booking.driver)
    )

    is_company_staff = (
        user.role in {
            'company_manager',
            'company_auditor',
            'company_operator',
        }
        and user.company_id == booking.route.company_id
        and can_handle_route(user, booking.route_id)
    )

    is_platform_admin = user.is_superuser

    if not (
        is_passenger
        or is_assigned_driver
        or is_company_staff
        or is_platform_admin
    ):
        return _not_yours(user, booking)

    if (
        booking.status in ('cancelled', 'no_show', 'completed')
        and not is_platform_admin
        and not _passenger_can_track(booking)
    ):
        return Response(
            {'error': 'This booking is no longer active.'},
            status=status.HTTP_409_CONFLICT,
        )

    # Passenger live tracking is available only for a confirmed,
    # actively boarding or departed trip with an assigned driver.
    # Preserve the existing access rules for staff, drivers and admins.
    if is_passenger and not is_platform_admin:
        trip_status = (
            str(booking.trip.status or '').lower()
            if booking.trip else ''
        )
        if (
            not _passenger_can_track(booking)
            or trip_status not in ('boarding', 'departed')
            or booking.driver_id is None
        ):
            return Response(
                {
                    'error': (
                        'Live tracking is available only when your '
                        'confirmed trip is boarding or departed and '
                        'has an assigned driver.'
                    ),
                    'trip_status': trip_status or None,
                },
                status=status.HTTP_409_CONFLICT,
            )

    driver = booking.driver
    passenger_user = booking.user

    def to_float(value):
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    p_lat = to_float(booking.passenger_latitude)
    p_lng = to_float(booking.passenger_longitude)
    d_lat = to_float(driver.latitude) if driver else None
    d_lng = to_float(driver.longitude) if driver else None

    distance_km = None
    if None not in (p_lat, p_lng, d_lat, d_lng):
        from math import radians, sin, cos, asin, sqrt
        dlat = radians(d_lat - p_lat)
        dlng = radians(d_lng - p_lng)
        a = (
            sin(dlat / 2) ** 2
            + cos(radians(p_lat)) * cos(radians(d_lat)) * sin(dlng / 2) ** 2
        )
        distance_km = round(6371.0 * 2 * asin(sqrt(a)), 2)

    can_see_contacts = (
        ((is_passenger or is_assigned_driver)
         and (
             booking.status in ('pending', 'confirmed')
             or _passenger_can_track(booking)
         )
         # Unpaid cash holds last the whole trip and cost nothing, so they
         # see the bus but not the driver's phone number.
         and not (
             is_passenger
             and cash_due_on_board(booking, getattr(booking, 'payment', None))
         ))
        or is_company_staff
        or is_platform_admin
    )

    route_obj = booking.route
    route_payload = None
    stage_payload = []
    if route_obj:
        route_payload = {
            'id': route_obj.id,
            'name': route_obj.name,
            'start_point': route_obj.start_point,
            'end_point': route_obj.end_point,
            'geometry': route_obj.geometry,
        }
        for st in route_obj.pickup_stages.filter(is_active=True).order_by('order', 'id'):
            stage_payload.append({
                'id': st.id,
                'name': st.name,
                'order': st.order,
                'latitude': to_float(st.latitude),
                'longitude': to_float(st.longitude),
            })

    stage_obj = booking.pickup_stage
    pickup_payload = None
    if stage_obj:
        pickup_payload = {
            'id': stage_obj.id,
            'name': stage_obj.name,
            'order': stage_obj.order,
            'latitude': to_float(stage_obj.latitude),
            'longitude': to_float(stage_obj.longitude),
        }
    elif booking.pickup_location:
        pickup_payload = {
            'id': None,
            'name': booking.pickup_location,
            'order': None,
            'latitude': None,
            'longitude': None,
        }

    return Response(
        {
            'booking_id': booking.id,
            'booking_number': booking.booking_number,
            'status': booking.status,
            'distance_km': distance_km,
            'contacts_visible': can_see_contacts,
            'route': route_payload,
            'stages': stage_payload,
            'traffic': _route_traffic_payload(route_obj, booking.driver_id),
            'pickup': pickup_payload,
            'departure_at': booking.trip.departure_at if booking.trip else None,
            'trip_status': booking.trip.status if booking.trip else None,
            'incident': _active_incident_payload(booking),

            'passenger': {
                'name': passenger_user.display_name,
                'phone': (
                    passenger_user.phone_number
                    if can_see_contacts else None
                ),
                'latitude': p_lat,
                'longitude': p_lng,
            },

            'driver': {
                'driver_id': driver.id if driver else None,
                'name': driver.name if driver else None,
                'phone': (
                    driver.phone_number
                    if driver and can_see_contacts else None
                ),
                'bus_number': _bus_number(booking.trip, driver),
                'latitude': d_lat,
                'longitude': d_lng,
                'location_updated_at': (
                    driver.location_updated_at
                    if driver
                    else None
                ),
            },
            'boarded': hasattr(booking, 'boarding_event'),
            **location_freshness_for_booking(booking_id),
        },
        status=status.HTTP_200_OK,
    )


def _reroute_goal_point(booking, goal):
    """(lat, lng) of the passenger's pickup stage or the route's end, or None."""
    if goal == 'pickup':
        stage = booking.pickup_stage
        return (float(stage.latitude), float(stage.longitude)) if stage else None
    return _route_end_point(booking.route)


def _route_end_point(route):
    if route.end_latitude is not None and route.end_longitude is not None:
        return (float(route.end_latitude), float(route.end_longitude))
    last_stage = (
        route.pickup_stages.filter(is_active=True).order_by('order', 'id').last()
    )
    if last_stage is None:
        return None
    return (float(last_stage.latitude), float(last_stage.longitude))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([BusRerouteThrottle])
def booking_reroute(request, booking_id):
    """Road from where the bus is now to the pickup stage or the route's end.

    The passenger's map asks for this when the bus has left its planned route.
    Both ends come from the server, so a caller cannot route arbitrary points
    through the road service. Buses in the same 100 m or so share one answer.
    """
    from django.core.cache import cache
    from companies.routing import RoutingError, road_line
    from .live_signals import location_freshness, trip_is_live

    booking = (
        Booking.objects
        .select_related('route', 'driver', 'trip', 'pickup_stage')
        .filter(id=booking_id)
        .first()
    )
    if not booking:
        return Response(
            {'error': 'Booking not found'},
            status=status.HTTP_404_NOT_FOUND,
        )
    if booking.user_id != request.user.id and not request.user.is_superuser:
        return _not_yours(request.user, booking)

    goal = request.query_params.get('goal')
    if goal not in ('pickup', 'destination'):
        return Response(
            {'error': 'goal must be pickup or destination.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    driver = booking.driver
    if (
        not _passenger_can_track(booking)
        or driver is None
        or not trip_is_live(booking.trip)
        or location_freshness(driver)['is_stale']
    ):
        return Response(
            {'error': 'This bus has no live location to route from.'},
            status=status.HTTP_409_CONFLICT,
        )

    target = _reroute_goal_point(booking, goal)
    if target is None:
        return Response(
            {'error': 'This trip has no location for that goal.'},
            status=status.HTTP_409_CONFLICT,
        )

    bus = (float(driver.latitude), float(driver.longitude))
    cache_key = (
        f'bus-reroute:{target[0]:.5f},{target[1]:.5f}:'
        f'{bus[0]:.3f},{bus[1]:.3f}'
    )
    payload = cache.get(cache_key)
    if payload is None:
        try:
            geometry, distance_m = road_line([bus, target], timeout=8)
        except RoutingError as exc:
            return Response(
                {'error': str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        payload = {'geometry': geometry, 'distance_m': round(distance_m)}
        cache.set(cache_key, payload, BUS_REROUTE_CACHE_SECONDS)

    return Response({**payload, 'goal': goal}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([BusRerouteThrottle])
def driver_reroute(request, driver_id):
    """Road from the driver's last fix to the end of their live trip's route.

    The driver's map asks for this when the bus has left its planned route, so
    the bus is drawn on a real road. Only the driver's own account may ask.
    """
    from django.core.cache import cache
    from companies.routing import RoutingError, road_line
    from .live_signals import location_freshness, trip_is_live

    driver = Driver.objects.filter(id=driver_id).first()
    if not driver:
        return Response({'error': 'Driver not found'}, status=status.HTTP_404_NOT_FOUND)
    user = request.user
    if not (user.is_superuser or (user.role == 'driver' and is_driver_account_for(user, driver))):
        return Response({'error': 'Not authorized for this driver.'}, status=status.HTTP_403_FORBIDDEN)

    # Same trip the driver's map shows (get_driver_bookings): boarding first.
    trips = Trip.objects.select_related('route').filter(driver_id=driver.id)
    trip = (
        trips.filter(status='boarding').order_by('departure_at', 'id').first()
        or trips.filter(status='departed').order_by('-departure_at', '-id').first()
    )
    if not trip_is_live(trip) or location_freshness(driver)['is_stale']:
        return Response(
            {'error': 'This bus has no live location to route from.'},
            status=status.HTTP_409_CONFLICT,
        )
    target = _route_end_point(trip.route)
    if target is None:
        return Response(
            {'error': 'This trip has no location for that goal.'},
            status=status.HTTP_409_CONFLICT,
        )

    bus = (float(driver.latitude), float(driver.longitude))
    cache_key = (
        f'bus-reroute:{target[0]:.5f},{target[1]:.5f}:'
        f'{bus[0]:.3f},{bus[1]:.3f}'
    )
    payload = cache.get(cache_key)
    if payload is None:
        try:
            geometry, distance_m = road_line([bus, target], timeout=8)
        except RoutingError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        payload = {'geometry': geometry, 'distance_m': round(distance_m)}
        cache.set(cache_key, payload, BUS_REROUTE_CACHE_SECONDS)

    return Response({**payload, 'goal': 'destination'}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_passenger_location(request, booking_id):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    try:
        booking = Booking.objects.select_related('trip').get(
            id=booking_id,
            user=request.user,
        )
    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    trip_status = (
        str(booking.trip.status or '').lower()
        if booking.trip else ''
    )
    if (
        not _passenger_can_track(booking)
        or trip_status not in ('boarding', 'departed')
        or booking.driver_id is None
    ):
        return Response(
            {
                'error': (
                    'Location sharing starts when your confirmed trip '
                    'is boarding or departed and has an assigned driver.'
                ),
                'trip_status': trip_status or None,
            },
            status=status.HTTP_409_CONFLICT,
        )

    serializer = PassengerLocationSerializer(
        data=request.data
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    booking.passenger_latitude = (
        serializer.validated_data['latitude']
    )

    booking.passenger_longitude = (
        serializer.validated_data['longitude']
    )

    booking.save(
        update_fields=[
            'passenger_latitude',
            'passenger_longitude'
        ]
    )

    return Response(
        {'message': 'Location updated'},
        status=status.HTTP_200_OK
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_stage_departure(request, booking_id):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    try:
        booking = Booking.objects.select_related(
            'route__company'
        ).get(
            id=booking_id
        )
    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    user = request.user

    # Stage departure may be updated by:
    # - Django superusers
    # - Company Managers for their own company
    # - Company Operators for their own company
    #
    # Company Auditors are read-only.
    # Passengers and Drivers cannot change stage departure.
    is_allowed = (
        user.is_superuser
        or (
            user.role in {
                'company_manager',
                'company_operator',
            }
            and user.company_id == booking.route.company_id
            # A route-restricted operator may only act on their assigned
            # routes (matches verify_boarding / cash / walk-in / trips).
            and can_handle_route(user, booking.route_id)
        )
    )

    if not is_allowed:
        return Response(
            {'error': 'Manager or Operator authorization required'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        minutes = int(
            request.data.get('minutes')
        )
    except (TypeError, ValueError):
        return Response(
            {'error': 'Enter valid minutes'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not 0 <= minutes <= 720:
        return Response(
            {'error': 'Minutes must be between 0 and 720.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    booking.stage_departure_at = (
        timezone.now()
        + timezone.timedelta(minutes=minutes)
    )

    booking.save(
        update_fields=['stage_departure_at']
    )

    return Response(
        {
            'message': 'Stage departure updated',
            'stage_departure_at': (
                booking.stage_departure_at
            ),
        },
        status=status.HTTP_200_OK
    )



# ============================================================
# INCIDENT MANAGEMENT
# ============================================================

COMPANY_INCIDENT_ROLES = {
    'company_manager',
    'company_auditor',
    'company_operator',
}


def _can_access_incident(user, incident):
    """
    Check whether a user may access an incident.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    company_id = incident.trip.route.company_id

    if user.role in COMPANY_INCIDENT_ROLES:
        company_access = (
            user.company_id is not None
            and user.company_id == company_id
        )
        if not company_access:
            return False
        route_ids = operator_route_ids(user)
        return route_ids is None or incident.trip.route_id in route_ids

    if user.role == 'driver':
        return (
            incident.trip.driver is not None
            and is_driver_account_for(user, incident.trip.driver)
        )

    return False


def _can_report_incident(user, trip):
    """
    Check whether a user may report an incident for a trip.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    company_id = trip.route.company_id

    if user.role in {'company_manager', 'company_operator'}:
        company_access = (
            user.company_id is not None
            and user.company_id == company_id
        )
        if not company_access:
            return False
        route_ids = operator_route_ids(user)
        return route_ids is None or trip.route_id in route_ids

    if user.role == 'driver':
        return (
            trip.driver is not None
            and is_driver_account_for(user, trip.driver)
        )

    return False


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def incident_list(request):
    """
    List incidents visible to the authenticated user.
    """
    user = request.user

    queryset = Incident.objects.select_related(
        'trip',
        'trip__route',
        'trip__route__company',
        'trip__driver',
        'reported_by',
    )

    if user.is_superuser:
        pass

    elif user.role in COMPANY_INCIDENT_ROLES:
        if user.company_id is None:
            return Response(
                {'error': 'Company assignment required.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        queryset = queryset.filter(
            trip__route__company_id=user.company_id
        )
        if user.role == 'company_operator':
            route_ids = operator_route_ids(user)
            if route_ids is not None:
                queryset = queryset.filter(trip__route_id__in=route_ids)

    elif user.role == 'driver':
        queryset = queryset.filter(
            trip__driver__in=drivers_for_user(user)
        )

    else:
        return Response(
            {'error': 'You are not authorized to view incidents.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    return Response(
        IncidentSerializer(queryset, many=True).data,
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def report_incident(request):
    """
    Report an incident against a trip.
    """
    trip_id = request.data.get('trip_id')

    if isinstance(trip_id, bool) or not str(trip_id or '').strip().isdigit():
        return Response(
            {'error': 'trip_id is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    trip_id = parse_id(trip_id)
    if trip_id is None:
        return Response(
            {'error': 'trip_id must be a valid id.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        trip = Trip.objects.select_related(
            'route',
            'route__company',
            'driver',
        ).get(id=int(str(trip_id).strip()))
    except Trip.DoesNotExist:
        return Response(
            {'error': 'Trip not found.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if not _can_report_incident(request.user, trip):
        return Response(
            {
                'error':
                'You are not authorized to report an incident '
                'for this trip.'
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    incident_type = request.data.get('incident_type')
    description = request.data.get('description')

    valid_types = {
        choice[0]
        for choice in Incident.INCIDENT_TYPE_CHOICES
    }

    if not isinstance(incident_type, str) or incident_type not in valid_types:
        return Response(
            {
                'error': 'Invalid incident_type.',
                'valid_types': sorted(valid_types),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        description = free_text(description, 'what happened', min_letters=5, max_length=2000)
    except DjangoValidationError as e:
        return Response({'error': e.messages[0]}, status=status.HTTP_400_BAD_REQUEST)

    incident = Incident.objects.create(
        trip=trip,
        reported_by=request.user,
        incident_type=incident_type,
        description=str(description).strip(),
    )

    return Response(
        IncidentSerializer(incident).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def incident_detail(request, incident_id):
    """
    View or update an incident.

    Only Company Managers and superusers may update incidents.
    """
    try:
        incident = Incident.objects.select_related(
            'trip',
            'trip__route',
            'trip__route__company',
            'trip__driver',
            'reported_by',
        ).get(id=incident_id)
    except Incident.DoesNotExist:
        return Response(
            {'error': 'Incident not found.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if not _can_access_incident(request.user, incident):
        return Response(
            {
                'error':
                'You are not authorized to access this incident.'
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == 'GET':
        return Response(
            IncidentSerializer(incident).data,
            status=status.HTTP_200_OK,
        )

    user = request.user

    allowed_to_update = (
        user.is_superuser
        or (
            user.role == 'company_manager'
            and user.company_id == incident.trip.route.company_id
        )
    )

    if not allowed_to_update:
        return Response(
            {
                'error':
                'Only a Company Manager can update incidents.'
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    allowed_statuses = {
        choice[0]
        for choice in Incident.STATUS_CHOICES
    }

    new_status = request.data.get('status')
    description = request.data.get('description')

    if new_status is not None:
        new_status = str(new_status).strip().lower()

        if new_status not in allowed_statuses:
            return Response(
                {
                    'error': 'Invalid status.',
                    'valid_statuses': sorted(allowed_statuses),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        incident.status = new_status

    if description is not None:
        try:
            description = free_text(description, 'what happened', min_letters=5, max_length=2000)
        except DjangoValidationError as e:
            return Response({'error': e.messages[0]}, status=status.HTTP_400_BAD_REQUEST)

        incident.description = description

    incident.save()

    return Response(
        IncidentSerializer(incident).data,
        status=status.HTTP_200_OK,
    )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_driver_bookings(request, driver_id):
    """
    Return the driver's active/next trip as one route-centric payload.

    The driver follows the Trip's stored Route.geometry.
    Passenger bookings are assignments to pickup stages on that route.

    A booking never creates, changes, or reroutes the driver's geometry.
    """

    from django.utils import timezone
    from companies.models import Trip

    driver = (
        Driver.objects
        .select_related("company")
        .filter(id=driver_id)
        .first()
    )

    if not driver:
        return Response(
            {"error": "Driver not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    user = request.user

    allowed = (
        user.is_superuser
        or can_access_company(user, driver.company_id)
        or (
            user.role == "driver"
            and is_driver_account_for(user, driver)
        )
    )

    if not allowed:
        return Response(
            {"error": "Not authorized for this driver."},
            status=status.HTTP_403_FORBIDDEN,
        )

    now = timezone.now()

    # ----------------------------------------------------------
    # DRIVER'S ACTIVE TRIP
    # ----------------------------------------------------------
    # "boarding" is the explicit state meaning the driver has
    # started operating this trip.
    # ----------------------------------------------------------

    import datetime as _dt

    _driver_trips = (
        Trip.objects
        .filter(driver_id=driver_id)
        .select_related("route", "route__company", "driver")
    )

    # Prefer a boarding trip; otherwise keep serving a trip that has
    # already departed (and is still on the road) so the driver's map
    # does not lose its route mid-journey.
    trip = (
        _driver_trips
        .filter(
            status="boarding",
            departure_at__gte=now - _dt.timedelta(hours=12),
        )
        .order_by("departure_at", "id")
        .first()
    ) or (
        _driver_trips
        .filter(
            status="departed",
            departure_at__gte=now - _dt.timedelta(hours=12),
        )
        .order_by("-departure_at", "-id")
        .first()
    )

    # CONNECT-FIX: scheduled-trip fallback
    # Nothing boarding or on the road: serve the driver's next scheduled
    # trip so the map can show its route and pickup stages.
    if not trip:
        trip = (
            _driver_trips
            .filter(
                status="scheduled",
                departure_at__gte=now - _dt.timedelta(hours=1),
                departure_at__lte=now + _dt.timedelta(hours=24),
            )
            .order_by("departure_at", "id")
            .first()
        )

    if not trip:
        return Response(
            {
                "driver": {
                    "id": driver.id,
                    "name": driver.name,
                    "phone_number": driver.phone_number,
                    "bus_number": driver.bus_number,
                    "company_id": driver.company_id,
                    "company_name": (
                        driver.company.name
                        if driver.company
                        else None
                    ),
                    "latitude": (
                        float(driver.latitude)
                        if driver.latitude is not None
                        else None
                    ),
                    "longitude": (
                        float(driver.longitude)
                        if driver.longitude is not None
                        else None
                    ),
                    "location_updated_at": (
                        driver.location_updated_at
                    ),
                },
                "active_trip": None,
                "bookings": [],
            },
            status=status.HTTP_200_OK,
        )

    # A route-restricted operator reads passengers only on routes they handle.
    if not can_handle_route(user, trip.route_id):
        return Response(
            {"error": "Not authorized for this route."},
            status=status.HTTP_403_FORBIDDEN,
        )

    route = trip.route

    # ----------------------------------------------------------
    # ALL BOOKINGS FOR THIS TRIP
    # ----------------------------------------------------------
    bookings = (
        Booking.objects
        .filter(
            trip_id=trip.id,
            status__in=["pending", "confirmed", "completed"],
        )
        .select_related(
            "user",
            "pickup_stage",
            "payment",
        )
        .prefetch_related("seat_assignments")
        .order_by(
            "pickup_stage__order",
            "created_at",
            "id",
        )
    )

    booking_data = []

    for booking in bookings:
        pickup_stage = booking.pickup_stage

        booking_data.append({
            "booking_id": booking.id,
            "booking_number": booking.booking_number,
            "seats": booking.seats,
            "total_amount": str(booking.total_amount),
            "seat_numbers": sorted(a.seat_no for a in booking.seat_assignments.all()),
            "status": booking.status,
            "passenger": booking.user.display_name,
            "passenger_name": (
                booking.user.get_full_name().strip()
                or ((booking.user.phone_number or "")[:6] + "…" + (booking.user.phone_number or "")[-3:])
            ),
            "passenger_phone": booking.user.phone_number,

            "trip_id": trip.id,
            "departure_at": trip.departure_at,

            "company_id": route.company_id,
            "company_name": (
                route.company.name
                if route.company
                else None
            ),

            "route": route.name,
            "route_id": route.id,

            "pickup_location": booking.pickup_location,

            "pickup_stage_id": (
                pickup_stage.id
                if pickup_stage
                else None
            ),
            "pickup_stage_name": (
                pickup_stage.name
                if pickup_stage
                else None
            ),
            "pickup_stage_order": (
                pickup_stage.order
                if pickup_stage
                else None
            ),
            "pickup_latitude": (
                float(pickup_stage.latitude)
                if pickup_stage
                and pickup_stage.latitude is not None
                else None
            ),
            "pickup_longitude": (
                float(pickup_stage.longitude)
                if pickup_stage
                and pickup_stage.longitude is not None
                else None
            ),

            "passenger_latitude": (
                float(booking.passenger_latitude)
                if booking.passenger_latitude is not None
                else None
            ),
            "passenger_longitude": (
                float(booking.passenger_longitude)
                if booking.passenger_longitude is not None
                else None
            ),

            "payment_status": (
                booking.payment.status
                if hasattr(booking, "payment")
                else "unpaid"
            ),
            "payment_method": (
                booking.payment.method
                if hasattr(booking, "payment")
                else None
            ),
        })

    # ----------------------------------------------------------
    # ALL ACTIVE PICKUP STAGES ON THE FIXED ROUTE
    # ----------------------------------------------------------
    stage_bookings = {}

    for booking in booking_data:
        stage_id = booking["pickup_stage_id"]

        if stage_id is not None:
            stage_bookings.setdefault(stage_id, []).append(booking)

    stages = []

    for stage in (
        route.pickup_stages
        .filter(is_active=True)
        .order_by("order", "id")
    ):
        passengers = stage_bookings.get(stage.id, [])

        stages.append({
            "id": stage.id,
            "name": stage.name,
            "order": stage.order,
            "latitude": float(stage.latitude),
            "longitude": float(stage.longitude),
            "source": stage.source,
            "booking_count": len(passengers),
            "passenger_count": sum(
                item["seats"]
                for item in passengers
            ),
            "passengers": passengers,
        })

    # ----------------------------------------------------------
    # ONE DRIVER-CENTRIC ACTIVE TRIP PAYLOAD
    # ----------------------------------------------------------
    active_trip = {
        "id": trip.id,
        "trip_id": trip.id,
        "departure_at": trip.departure_at,
        "status": trip.status,

        "company_id": route.company_id,
        "company_name": (
            route.company.name
            if route.company
            else None
        ),

        "route_id": route.id,
        "route": route.name,
        "route_name": route.name,

        "route_start_point": route.start_point,
        "route_end_point": route.end_point,

        "route_start_latitude": (
            float(route.start_latitude)
            if route.start_latitude is not None
            else None
        ),
        "route_start_longitude": (
            float(route.start_longitude)
            if route.start_longitude is not None
            else None
        ),
        "route_end_latitude": (
            float(route.end_latitude)
            if route.end_latitude is not None
            else None
        ),
        "route_end_longitude": (
            float(route.end_longitude)
            if route.end_longitude is not None
            else None
        ),

        # AUTHORITATIVE NAVIGATION GEOMETRY.
        # NEVER build this from passenger bookings.
        "route_geometry": (
            route.geometry
            or {
                "type": "LineString",
                "coordinates": [],
            }
        ),

        "stages": stages,
        "bookings": booking_data,

        "booking_count": len(booking_data),
        "passenger_count": sum(
            booking["seats"]
            for booking in booking_data
        ),
    }

    driver_data = {
        "id": driver.id,
        "name": driver.name,
        "phone_number": driver.phone_number,
        "bus_number": driver.bus_number,
        "company_id": driver.company_id,
        "company_name": (
            driver.company.name
            if driver.company
            else None
        ),
        "latitude": (
            float(driver.latitude)
            if driver.latitude is not None
            else None
        ),
        "longitude": (
            float(driver.longitude)
            if driver.longitude is not None
            else None
        ),
        "location_updated_at": driver.location_updated_at,
    }

    return Response(
        {
            "driver": driver_data,
            "active_trip": active_trip,
            "bookings": booking_data,
        },
        status=status.HTTP_200_OK,
    )

# ============================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def auditor_receipt_search(request):
    """
    Read-only receipt/payment investigation for company auditors.

    Search by:
    - booking number
    - payment/provider reference
    - username
    - phone number

    Results are restricted to the auditor's company.
    """
    if request.user.role != 'company_auditor':
        return Response(
            {'error': 'Only company auditors can access this endpoint.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    company_id = getattr(request.user, 'company_id', None)

    if not company_id:
        return Response(
            {'error': 'Auditor is not assigned to a company.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    search = (request.query_params.get('search') or '').strip()

    if not search:
        return Response(
            {
                'error': (
                    'Enter a receipt, booking, payment reference, '
                    'username, or phone number.'
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    bookings = (
        Booking.objects
        .filter(route__company_id=company_id)
        .select_related(
            'user',
            'route__company',
            'trip',
            'payment',
            'boarding_event',
            'financial_hold',
            'incident_resolution__incident',
        )
        .order_by('-created_at')
    )

    bookings = bookings.filter(
        Q(booking_number__icontains=search)
        | Q(payment__provider_reference__icontains=search)
        | Q(user__username__icontains=search)
        | Q(user__phone_number__icontains=search)
    )

    records = []

    for booking in bookings:
        payment = getattr(booking, 'payment', None)
        boarding = getattr(booking, 'boarding_event', None)
        hold = getattr(booking, 'financial_hold', None)
        resolution = getattr(booking, 'incident_resolution', None)

        passenger_name = booking.user.display_name

        activity = [
            {
                'type': 'booking_created',
                'label': 'Booking created',
                'timestamp': booking.created_at,
                'status': 'completed',
                'details': 'Booking was created.',
            }
        ]

        if payment:
            activity.append({
                'type': 'payment_started',
                'label': 'Payment initiated',
                'timestamp': payment.created_at,
                'status': payment.status,
                'reference': payment.provider_reference,
                'details': f'Payment method: {payment.method}.',
            })

            if payment.status == 'confirmed' and payment.confirmed_at:
                activity.append({
                    'type': 'payment_confirmed',
                    'label': 'Payment confirmed',
                    'timestamp': payment.confirmed_at,
                    'status': 'confirmed',
                    'reference': payment.provider_reference,
                    'details': 'Payment was confirmed.',
                })

            if payment.status == 'failed':
                activity.append({
                    'type': 'payment_failed',
                    'label': 'Payment failed',
                    'timestamp': payment.created_at,
                    'status': 'failed',
                    'reference': payment.provider_reference,
                    'details': (
                        'Payment is recorded as failed. '
                        'The current Payment model does not store '
                        'a separate failure-reason field.'
                    ),
                })

            if payment.refunded_at:
                activity.append({
                    'type': 'payment_refunded',
                    'label': 'Payment refunded',
                    'timestamp': payment.refunded_at,
                    'status': payment.refund_status,
                    'reference': payment.refund_reference,
                    'details': (
                        f'Refund amount: '
                        f'{payment.refund_amount or payment.amount}.'
                    ),
                })

        if hold:
            activity.append({
                'type': 'funds_held',
                'label': 'Funds held',
                'timestamp': hold.held_at,
                'status': hold.status,
                'details': f'Held amount: {hold.amount}.',
            })

            if hold.released_at:
                activity.append({
                    'type': 'funds_released',
                    'label': 'Funds released',
                    'timestamp': hold.released_at,
                    'status': 'released',
                    'details': 'Held funds were released.',
                })

            if hold.refunded_at:
                activity.append({
                    'type': 'hold_refunded',
                    'label': 'Held funds refunded',
                    'timestamp': hold.refunded_at,
                    'status': 'refunded',
                    'details': 'Held funds were refunded.',
                })

        if boarding:
            activity.append({
                'type': 'boarding_verified',
                'label': 'Boarding verified',
                'timestamp': boarding.verified_at,
                'status': 'confirmed',
                'details': (
                    f'Boarding verified using '
                    f'{boarding.method.upper()}.'
                ),
            })

        if booking.stage_departure_at:
            activity.append({
                'type': 'departure_staged',
                'label': 'Departure staged',
                'timestamp': booking.stage_departure_at,
                'status': 'completed',
                'details': 'Departure was staged.',
            })

        if booking.status == 'cancelled':
            activity.append({
                'type': 'booking_cancelled',
                'label': 'Booking cancelled',
                'timestamp': booking.updated_at,
                'status': 'cancelled',
                'details': 'Booking was cancelled.',
            })

        if booking.status == 'completed':
            activity.append({
                'type': 'booking_completed',
                'label': 'Journey completed',
                'timestamp': booking.updated_at,
                'status': 'completed',
                'details': 'Journey was completed.',
            })

        incident = None

        if resolution and resolution.incident:
            incident = {
                'incident_type': resolution.incident.incident_type,
                'incident_status': resolution.incident.status,
                'description': resolution.incident.description,
                'resolution': resolution.resolution,
                'resolution_status': resolution.status,
                'refund_amount': (
                    str(resolution.refund_amount)
                    if resolution.refund_amount is not None
                    else None
                ),
            }

        records.append({
            'booking_id': booking.id,
            'booking_number': booking.booking_number,

            'passenger': {
                'name': passenger_name,
                'username': booking.user.username,
                'phone_number': booking.user.phone_number,
            },

            'company': (
                booking.route.company.name
                if booking.route and booking.route.company
                else None
            ),

            'trip': {
                'trip_id': booking.trip_id,
                'route': booking.route.name if booking.route else None,
                'departure_at': (
                    booking.trip.departure_at
                    if booking.trip
                    else None
                ),
                'pickup_location': booking.pickup_location,
                'seats': booking.seats,
            },

            'booking': {
                'status': booking.status,
                'created_at': booking.created_at,
                'updated_at': booking.updated_at,
            },

            'payment': {
                'exists': bool(payment),
                'payment_id': payment.id if payment else None,
                'amount': (
                    str(payment.amount)
                    if payment
                    else str(booking.total_amount)
                ),
                'method': payment.method if payment else None,
                'status': payment.status if payment else 'unpaid',
                'settlement_status': (
                    payment.settlement_status
                    if payment
                    else None
                ),
                'provider_reference': (
                    payment.provider_reference
                    if payment
                    else None
                ),
                'confirmed_at': (
                    payment.confirmed_at
                    if payment
                    else None
                ),
                'created_at': (
                    payment.created_at
                    if payment
                    else None
                ),
                'refund_status': (
                    payment.refund_status
                    if payment
                    else None
                ),
                'refund_reference': (
                    payment.refund_reference
                    if payment
                    else None
                ),
                'refund_amount': (
                    str(payment.refund_amount)
                    if payment and payment.refund_amount is not None
                    else None
                ),
            },

            'hold': {
                'amount': str(hold.amount) if hold else None,
                'status': hold.status if hold else None,
                'held_at': hold.held_at if hold else None,
                'released_at': hold.released_at if hold else None,
                'refunded_at': hold.refunded_at if hold else None,
            },

            'boarding': {
                'verified': bool(boarding),
                'method': boarding.method if boarding else None,
                'verified_at': boarding.verified_at if boarding else None,
            },

            'incident': incident,

            'activity': sorted(
                activity,
                key=lambda item: item['timestamp'] or booking.created_at,
            ),
        })

    return Response(records, status=status.HTTP_200_OK)


# PASSENGER RECORDS / RECEIPTS / HISTORY
# ============================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def passenger_records(request):
    search = (request.query_params.get('search') or '').strip()

    bookings = (
        Booking.objects
        .filter(user=request.user)
        .select_related(
            'route__company',
            'trip__driver',
            'driver',
            'payment',
            'boarding_event',
            'financial_hold',
            'incident_resolution__incident',
        )
        .order_by('-created_at')
    )

    if search:
        bookings = bookings.filter(
            Q(booking_number__icontains=search)
            | Q(payment__provider_reference__icontains=search)
        )

    records = []

    for booking in bookings:
        payment = getattr(booking, 'payment', None)
        boarding = getattr(booking, 'boarding_event', None)
        hold = getattr(booking, 'financial_hold', None)
        resolution = getattr(booking, 'incident_resolution', None)

        activity = [{
            'type': 'booking_created',
            'label': 'Booking created',
            'timestamp': booking.created_at,
            'status': 'completed',
        }]

        if payment:
            activity.append({
                'type': 'payment_started',
                'label': 'Payment started',
                'timestamp': payment.created_at,
                'status': payment.status,
                'reference': payment.provider_reference,
            })

            if payment.status == 'confirmed' and payment.confirmed_at:
                activity.append({
                    'type': 'payment_confirmed',
                    'label': 'Payment confirmed',
                    'timestamp': payment.confirmed_at,
                    'status': 'confirmed',
                    'reference': payment.provider_reference,
                })

            if payment.status == 'failed':
                activity.append({
                    'type': 'payment_failed',
                    'label': 'Payment failed',
                    'timestamp': payment.created_at,
                    'status': 'failed',
                    'reference': payment.provider_reference,
                })

            if payment.refunded_at:
                activity.append({
                    'type': 'payment_refunded',
                    'label': 'Payment refunded',
                    'timestamp': payment.refunded_at,
                    'status': payment.refund_status,
                    'reference': payment.refund_reference,
                })

        if boarding:
            activity.append({
                'type': 'boarding_verified',
                'label': 'Boarding verified',
                'timestamp': boarding.verified_at,
                'status': 'confirmed',
            })

        if booking.status == 'cancelled':
            activity.append({
                'type': 'booking_cancelled',
                'label': 'Booking cancelled',
                'timestamp': booking.updated_at,
                'status': 'cancelled',
            })

        if booking.status == 'completed':
            activity.append({
                'type': 'booking_completed',
                'label': 'Journey completed',
                'timestamp': booking.updated_at,
                'status': 'completed',
            })

        incident = None
        if resolution:
            incident = {
                'incident_type': resolution.incident.incident_type,
                'incident_status': resolution.incident.status,
                'description': resolution.incident.description,
                'resolution': resolution.resolution,
                'resolution_status': resolution.status,
                'refund_amount': (
                    str(resolution.refund_amount)
                    if resolution.refund_amount is not None
                    else None
                ),
            }

        driver = booking.driver or (booking.trip.driver if booking.trip else None)
        # Phone only for passengers who actually paid or rode (lost property,
        # complaints); unpaid cash holds and cancelled bookings never see it.
        show_driver_phone = (
            booking.status in ('confirmed', 'completed')
            and not cash_due_on_board(booking, payment)
        )

        records.append({
            'booking_id': booking.id,
            'booking_number': booking.booking_number,

            'passenger': {
                'name': (
                    request.user.get_full_name()
                    or request.user.username
                ),
                'username': request.user.username,
                'phone_number': request.user.phone_number,
            },

            'trip': {
                'trip_id': booking.trip_id,
                'company': (
                    booking.route.company.name
                    if booking.route and booking.route.company
                    else None
                ),
                'route': booking.route.name if booking.route else None,
                'departure_at': (
                    booking.trip.departure_at
                    if booking.trip
                    else None
                ),
                'pickup_location': booking.pickup_location,
                'seats': booking.seats,
            },

            'driver': {
                'name': driver.name,
                'phone_number': (
                    driver.phone_number if show_driver_phone else None
                ),
                'bus_number': _bus_number(booking.trip, driver),
                'bus_plate': (
                    booking.trip.bus.registration_number
                    if booking.trip and booking.trip.bus_id else None
                ),
            } if driver else None,

            'booking': {
                'status': booking.status,
                'created_at': booking.created_at,
                'updated_at': booking.updated_at,
                'verification_pin': (
                    booking.verification_pin
                    if booking.status == 'confirmed'
                    or cash_due_on_board(booking, payment)
                    else None
                ),
            },

            'payment': {
                'exists': bool(payment),
                'payment_id': payment.id if payment else None,
                'amount': (
                    str(payment.amount)
                    if payment
                    else str(booking.total_amount)
                ),
                'method': payment.method if payment else None,
                'status': payment.status if payment else 'unpaid',
                'settlement_status': (
                    payment.settlement_status if payment else None
                ),
                'provider_reference': (
                    payment.provider_reference if payment else None
                ),
                'confirmed_at': (
                    payment.confirmed_at if payment else None
                ),
                'created_at': (
                    payment.created_at if payment else None
                ),
                'refund_status': (
                    payment.refund_status if payment else None
                ),
                'refund_reference': (
                    payment.refund_reference if payment else None
                ),
                'refund_amount': (
                    str(payment.refund_amount)
                    if payment and payment.refund_amount is not None
                    else None
                ),
            },

            'hold': {
                'amount': str(hold.amount) if hold else None,
                'status': hold.status if hold else None,
                'held_at': hold.held_at if hold else None,
                'released_at': hold.released_at if hold else None,
                'refunded_at': hold.refunded_at if hold else None,
            },

            'boarding': {
                'verified': bool(boarding),
                'method': boarding.method if boarding else None,
                'verified_at': boarding.verified_at if boarding else None,
            },

            'incident': incident,

            'activity': sorted(
                activity,
                key=lambda item: item['timestamp'] or booking.created_at
            ),
        })

    return Response(records, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def driver_end_trip(request, driver_id):
    """The driver ends their own active trip (boarding/departed -> completed)."""
    import datetime as _dt
    from django.db import transaction
    from django.utils import timezone
    from companies.models import Trip

    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    driver = Driver.objects.filter(id=driver_id).first()
    if not driver:
        return Response(
            {'error': 'Driver not found'},
            status=status.HTTP_404_NOT_FOUND,
        )

    user = request.user
    if not (
        user.is_superuser
        or is_driver_account_for(user, driver)
    ):
        return Response(
            {'error': 'Not authorized for this driver.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    trips = Trip.objects.filter(driver_id=driver_id)
    trip = (
        trips.filter(status='boarding').order_by('departure_at', 'id').first()
    ) or (
        trips.filter(
            status='departed',
        ).order_by('-departure_at', '-id').first()
    )

    if not trip:
        return Response(
            {'error': 'No active trip to end.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if trip.departure_at > timezone.now():
        return Response(
            {'error': 'This trip has not reached its departure time yet. '
                      'Report an incident or ask the company to cancel it.'},
            status=status.HTTP_409_CONFLICT,
        )

    from django.conf import settings as _settings
    min_minutes = getattr(_settings, 'TRIP_MIN_DURATION_MINUTES', 20)
    if (
        not user.is_superuser
        and trip.departure_at + _dt.timedelta(minutes=min_minutes) > timezone.now()
    ):
        return Response(
            {'error': f'A trip cannot be ended within {min_minutes} minutes of '
                      'departure. Report an incident if something went wrong.'},
            status=status.HTTP_409_CONFLICT,
        )

    from bookings.services import run_refund_claims, settle_unboarded_no_shows

    refund_claims = []

    with transaction.atomic():
        trip = Trip.objects.select_for_update().get(pk=trip.pk)
        if trip.status not in ('boarding', 'departed'):
            return Response(
                {'error': 'This trip is no longer active.'},
                status=status.HTTP_409_CONFLICT,
            )
        settled, protected = settle_unboarded_no_shows(
            trip, claims=refund_claims
        )
        trip.status = 'completed'
        trip.save(update_fields=['status'])

    # Paystack is called only after the trip lock has been released.
    run_refund_claims(refund_claims)

    return Response(
        {'message': 'Trip completed.', 'trip_id': trip.id, 'status': trip.status,
         'no_shows_settled': settled, 'incident_protected': protected},
        status=status.HTTP_200_OK,
    )


def _active_incident_payload(booking):
    """The trip's active incident, as the passenger should see it."""
    if booking.trip_id is None:
        return None

    if booking.status in ('cancelled', 'completed', 'no_show'):
        return None

    incident = (
        booking.trip.incidents
        .filter(status__in=('reported', 'investigating'))
        .order_by('-reported_at')
        .first()
    )

    if incident is None:
        return None

    resolution = IncidentResolution.objects.filter(booking=booking).first()

    return {
        'id': incident.id,
        'incident_type': incident.incident_type,
        'description': incident.description,
        'status': incident.status,
        'resolution': resolution.resolution if resolution else None,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def booking_replacement_trips(request, booking_id):
    """Trips an incident-affected passenger could move their booking to."""
    from django.utils import timezone
    from companies.models import Trip

    booking = (
        Booking.objects
        .select_related('trip')
        .filter(id=booking_id)
        .first()
    )

    if not booking:
        return Response(
            {'error': 'Booking not found'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if booking.user_id != request.user.id:
        return Response(
            {'error': 'Only the passenger who owns this booking can do this.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if booking.trip_id is None or booking.status in (
        'cancelled', 'completed', 'no_show'
    ):
        return Response([], status=status.HTTP_200_OK)

    has_incident = booking.trip.incidents.filter(
        status__in=('reported', 'investigating')
    ).exists()

    if not has_incident:
        return Response([], status=status.HTTP_200_OK)

    candidates = (
        Trip.objects
        .filter(
            route_id=booking.route_id,
            status='scheduled',
            departure_at__gt=timezone.now(),
        )
        .exclude(id=booking.trip_id)
        .order_by('departure_at')[:10]
    )

    result = []
    for trip in candidates:
        available = trip.capacity - seats_taken(trip)
        if booking.seats <= available:
            result.append({
                'id': trip.id,
                'departure_at': trip.departure_at,
                'available_seats': available,
            })

    return Response(result, status=status.HTTP_200_OK)


# ============================================================
# WALK-IN BOOKING AT THE FIRST STAGE
# ============================================================

def _get_or_create_walk_in_user(User, phone):
    """Find the account for a phone or create a password-less one.

    Two trips can walk in the same new phone at once and each trip lock is
    separate, so the loser of the insert race re-reads the winner's row
    instead of failing the whole booking. The insert runs in a savepoint so
    the caller's transaction (and its seat reservation) survives the clash.
    """
    for _ in range(5):
        passenger = User.objects.filter(phone_number=phone).first()
        if passenger is not None:
            return passenger
        base = f"walkin_{phone}".replace('+', '')
        username, n = base, 1
        while User.objects.filter(username=username).exists():
            n += 1
            username = f"{base}_{n}"
        try:
            with transaction.atomic():
                return User.objects.create_user(
                    username=username, phone_number=phone, password=None)
        except IntegrityError:
            continue
    raise IntegrityError('Could not create or find the walk-in account.')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def walk_in_booking(request, trip_id):
    """Operator/driver books and boards a cash passenger at the first stage.

    Leaves the same trail as a normal cash booking that is later boarded:
    booking completed, payment confirmed + settlement eligible, a
    BoardingEvent, and the passenger's boarded_count incremented.
    """
    from django.contrib.auth import get_user_model
    from django.db.models import F as _F
    from notifications import sms as _sms

    raw_seats = request.data.get('seats', 1)
    try:
        if isinstance(raw_seats, bool):
            raise ValueError
        text = str(raw_seats).strip()
        if not text.isascii():
            raise ValueError
        seats = int(text)
    except (TypeError, ValueError):
        return Response({'error': 'seats must be a whole number.'},
                        status=status.HTTP_400_BAD_REQUEST)
    if seats < 1:
        return Response({'error': 'seats must be at least 1.'},
                        status=status.HTTP_400_BAD_REQUEST)
    if seats > settings.MAX_SEATS_PER_BOOKING:
        return _seat_limit(
            f'You can book at most {settings.MAX_SEATS_PER_BOOKING} seats at a time.')

    try:
        phone = kenyan_mobile(request.data.get('phone_number'))
    except DjangoValidationError as e:
        return Response({'error': 'Passenger phone: ' + e.messages[0]},
                        status=status.HTTP_400_BAD_REQUEST)

    User = get_user_model()
    actor = request.user

    with transaction.atomic():
        trip = (
            Trip.objects.select_for_update(of=('self',))
            .select_related('route', 'driver')
            .filter(pk=trip_id).first()
        )
        if trip is None:
            return Response({'error': 'Trip not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        authorized = (
            actor.is_superuser
            or (
                actor.role in {'company_manager', 'company_operator'}
                and actor.company_id == trip.route.company_id
                and can_handle_route(actor, trip.route_id)
            )
            or is_driver_account_for(actor, trip.driver)
        )
        if not authorized:
            return Response(
                {'error': 'You cannot book passengers on this trip.'},
                status=status.HTTP_403_FORBIDDEN)

        # Open once the stage is boarding, or once online booking has closed.
        walk_up_open = trip.status == 'boarding' or (
            trip.status == 'scheduled'
            and timezone.now() >= booking_closes_at(trip)
        )
        if not walk_up_open or trip_has_departed(trip):
            return Response(
                {'error': 'Walk-in booking is only available while the '
                          'trip is boarding or after online booking has '
                          'closed.'},
                status=status.HTTP_409_CONFLICT)

        stage = (
            PickupStage.objects
            .filter(route_id=trip.route_id, is_active=True)
            .order_by('order', 'id').first()
        )
        if stage is None:
            return Response({'error': 'This route has no active first stage.'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            remaining = reserve_seats(trip, seats)
        except NotEnoughSeats as exc:
            return Response(
                {'error': f'Not enough seats available. Only {exc.available} remaining.'},
                status=status.HTTP_400_BAD_REQUEST)

        passenger = _get_or_create_walk_in_user(User, phone)
        if passenger.role != 'passenger' or passenger.is_superuser:
            return Response(
                {'error': 'That phone number belongs to a staff account.'},
                status=status.HTTP_400_BAD_REQUEST)

        total = trip.route.price * Decimal(str(seats))
        booking = Booking.objects.create(
            user=passenger, route=trip.route, driver=trip.driver, trip=trip,
            pickup_location=stage.name, pickup_stage=stage, seats=seats,
            total_amount=total, status='completed',
        )
        Payment.objects.create(
            booking=booking, amount=total, method='cash', status='confirmed',
            settlement_status='eligible', confirmed_at=timezone.now(),
            provider_reference=None, idempotency_key=None,
            refund_status='not_requested',
        )
        wanted = request.data.get('seat_numbers')
        if wanted is not None and not isinstance(wanted, list):
            transaction.set_rollback(True)
            return Response({'error': 'seat_numbers must be a list of seat numbers.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            assign_seats(trip, booking, wanted)
        except SeatError as exc:
            transaction.set_rollback(True)
            return Response({'error': str(exc), 'code': 'seat_taken'},
                            status=status.HTTP_409_CONFLICT)
        BoardingEvent.objects.create(
            booking=booking, trip=trip, method='walkin', verified_by=actor)
        User.objects.filter(pk=passenger.pk).update(
            boarded_count=_F('boarded_count') + 1)

        number = booking.booking_number
        transaction.on_commit(
            lambda: _sms.send_booking_sms(passenger.phone_number, number))

    return Response({
        'message': 'Walk-in passenger booked and boarded.',
        'booking_id': booking.id,
        'booking_number': number,
        'seats': seats,
        'amount': str(total),
        'pickup_stage': stage.name,
        'seats_remaining': remaining,
    }, status=status.HTTP_201_CREATED)


from users.route_scope import (  # noqa: E402
    can_handle_route,
)


# ============================================================
# STAFF ALERT FEED (derived; limited to the routes the staff member handles)
# ============================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def staff_alerts(request):
    """Cross-company alert feed for manager/operators, scoped to operator routes.

    Derived from existing rows (no new table): cash payments awaiting
    confirmation and confirmed bookings created in the last 24 hours, on trips
    that are scheduled or boarding. Route-restricted operators only see their
    assigned routes.
    """
    from datetime import timedelta

    user = request.user
    if (
        not user.is_authenticated
        or (
            not user.is_superuser
            and user.role not in {'company_manager', 'company_operator'}
        )
        or not user.company_id
    ):
        return Response(
            {'error': 'Company staff authorization required'},
            status=status.HTTP_403_FORBIDDEN)

    base = (
        Booking.objects
        .filter(
            route__company_id=user.company_id,
            trip__status__in=['scheduled', 'boarding'],
        )
        .select_related('route', 'trip')
    )

    scope = operator_route_ids(user)
    if scope is not None:
        base = base.filter(route_id__in=scope)

    cash = base.filter(
        status='pending',
        payment__method='cash',
        payment__status='pending',
    )
    fresh = base.filter(
        status='confirmed',
        created_at__gte=timezone.now() - timedelta(hours=24),
    )

    rows = []
    for kind, qs in (('cash_pending', cash), ('new_booking', fresh)):
        for b in qs.order_by('-created_at')[:20]:
            rows.append((b.created_at, {
                'type': kind,
                'booking_id': b.id,
                'booking_number': b.booking_number,
                'route_id': b.route_id,
                'route_name': b.route.name,
                'seats': b.seats,
                'total_amount': str(b.total_amount),
                'trip_id': b.trip_id,
                'trip_departure': b.trip.departure_at,
                'created_at': b.created_at,
            }))
    rows.sort(key=lambda r: r[0], reverse=True)
    items = [r[1] for r in rows[:20]]
    return Response({'count': len(items), 'items': items})


# ============================================================
# SEAT MAP
# ============================================================

def _seat_staff(user, trip):
    """Company staff who may see names and block seats on this trip."""
    return user.is_superuser or (
        user.role in {'company_manager', 'company_operator'}
        and user.company_id == trip.route.company_id
        and can_handle_route(user, trip.route_id)
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def trip_seat_map(request, trip_id):
    try:
        trip = Trip.objects.select_related('route', 'driver', 'bus').get(pk=trip_id)
    except Trip.DoesNotExist:
        return Response({'error': 'Trip not found.'}, status=status.HTTP_404_NOT_FOUND)
    user = request.user
    staff = _seat_staff(user, trip) or (
        user.role == 'company_auditor' and user.company_id == trip.route.company_id
    )
    is_driver = trip.driver is not None and is_driver_account_for(user, trip.driver)
    mine = set(trip.bookings.filter(user=user).values_list('id', flat=True))
    data = seat_map(trip, viewer_booking_ids=mine, show_names=staff or is_driver)
    data['can_block'] = _seat_staff(user, trip) and trip.status in ('scheduled', 'boarding')
    return Response(data)


@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def trip_seat_block(request, trip_id, seat_no):
    from .models import SeatAssignment
    try:
        note = free_text(request.data.get('note'), 'the note', required=False,
                         min_letters=2, max_length=60)
    except DjangoValidationError as e:
        return Response({'error': e.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        try:
            trip = (
                Trip.objects.select_for_update()
                .select_related('route').get(pk=trip_id)
            )
        except Trip.DoesNotExist:
            return Response({'error': 'Trip not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not _seat_staff(request.user, trip):
            return Response({'error': 'Only the company’s operators can block seats.'},
                            status=status.HTTP_403_FORBIDDEN)
        if trip.status not in ('scheduled', 'boarding'):
            return Response({'error': f'Seats cannot change on a {trip.status} trip.'},
                            status=status.HTTP_409_CONFLICT)
        if not 1 <= seat_no <= trip.capacity:
            return Response({'error': f'Seat {seat_no} does not exist on this bus.'},
                            status=status.HTTP_400_BAD_REQUEST)

        if request.method == 'DELETE':
            trip.seat_assignments.filter(seat_no=seat_no, blocked=True).delete()
        else:
            purge_dead_rows(trip)
            if trip.seat_assignments.filter(seat_no=seat_no).exists():
                return Response({'error': f'Seat {seat_no} is already taken.'},
                                status=status.HTTP_409_CONFLICT)
            if seats_taken(trip) >= trip.capacity:
                return Response({'error': 'Every seat on this bus is already sold.'},
                                status=status.HTTP_409_CONFLICT)
            SeatAssignment.objects.create(
                trip=trip, seat_no=seat_no, blocked=True, blocked_by=request.user,
                note=note,
            )
        data = seat_map(trip, show_names=True)
    data['can_block'] = True
    return Response(data)
