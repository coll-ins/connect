from django.db.models import Q
import hmac
import hashlib
import json
import requests
import uuid

from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from rest_framework import status
from rest_framework.decorators import (
    api_view,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from companies.models import Trip, PickupStage
from .models import Incident, IncidentResolution
from users.permissions import can_manage_company, can_access_company
from notifications.sms import send_admin_alert_sms
from drivers.models import Driver
from wallets.models import Wallet, WalletTransaction

from .models import Booking, BookingHold, Payment, BoardingEvent
from .services import (
    settle_booking_fault,
    trip_has_departed,
    create_booking_hold,
    release_booking_hold,
)
from .serializers import (
    BookingCreateSerializer,
    AssignDriverSerializer,
    PassengerLocationSerializer,
    IncidentSerializer,
)
from users.identity import drivers_for_user, is_driver_account_for


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


# ============================================================
# PAYSTACK PAYMENT INITIALIZATION
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def initialize_paystack_payment(request, booking_id):
    """Initialize one Paystack checkout attempt for a booking."""
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
            getattr(request.user, 'email', None)
            or f"user_{request.user.id}@connect.local"
        ),
        'amount': amount_in_cents,
        'currency': 'KES',
        'reference': reference,
        'callback_url': (
            request.data.get('callback_url')
            if str(request.data.get('callback_url') or '').startswith(
                getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').rstrip('/') + '/'
            )
            else (
                f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')}"
                f"/passenger/payment/{booking.id}"
            )
        ),
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

            phone = (
                request.data.get('phone_number')
                or booking.user.phone_number
            )

            if not phone:
                return Response(
                    {'error': 'Enter an M-PESA phone number.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            phone = str(phone).strip()

            if (
                not phone.startswith('+254')
                or len(phone) != 13
                or not phone[1:].isdigit()
            ):
                return Response(
                    {
                        'error': (
                            'Enter a valid Kenyan phone number, '
                            'e.g. +254710000000.'
                        )
                    },
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
            or f'user_{request.user.id}@connect.local'
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

def _mark_payment_confirmed(payment, paystack_amount):
    """
    Confirm a Paystack payment and create the internal financial hold.

    The hold represents money received by CONNECT that is not yet
    eligible for company settlement.

    This function is idempotent:
    - Repeated webhook/verification calls do not create duplicate holds.
    """

    if payment.status in ('confirmed', 'refunded'):
        return True

    expected_amount = int(payment.amount * Decimal('100'))

    if int(paystack_amount) != expected_amount:
        payment.status = 'failed'
        payment.save(update_fields=['status'])
        return False

    booking = payment.booking

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

    if trip_has_departed(booking.trip) or booking.status in (
        'cancelled',
        'completed',
        'no_show',
    ):
        # Money arrived for a booking that cannot be used. The caller must
        # refund it after this transaction commits.
        if booking.status in ('pending', 'confirmed'):
            booking.status = 'cancelled'
            booking.save(update_fields=['status'])
        payment._needs_refund = True
        return True

    booking.status = 'confirmed'
    booking.save(update_fields=['status'])
    create_booking_hold(booking)

    return True

@api_view(['GET'])
@permission_classes([IsAuthenticated])
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
                timeout=30,
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
        ):
            with transaction.atomic():
                payment = (
                    Payment.objects
                    .select_for_update()
                    .select_related('booking')
                    .get(pk=payment.pk)
                )
                _mark_payment_confirmed(
                    payment,
                    data.get('amount', 0),
                )

            if getattr(payment, '_needs_refund', False):
                try:
                    settle_booking_fault(payment.booking, fault_party='company')
                except Exception:
                    _alert_payment_problem(
                        payment.provider_reference,
                        'late payment confirmed but the automatic refund failed',
                    )
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

    if data.get('status') == 'success':
        with transaction.atomic():
            payment = Payment.objects.select_for_update().select_related('booking').get(pk=payment.pk)
            _mark_payment_confirmed(payment, data.get('amount', 0))

        if getattr(payment, '_needs_refund', False):
            try:
                settle_booking_fault(payment.booking, fault_party='company')
            except Exception:
                _alert_payment_problem(
                    payment.provider_reference,
                    'late payment confirmed but the automatic refund failed',
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

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    # Paystack allows ONE webhook URL per mode, so refund events arrive here.
    # The refund handler re-verifies the signature itself.
    if str(event.get('event', '')).startswith('refund.'):
        return paystack_refund_webhook(request)

    if event.get('event') != 'charge.success':
        return HttpResponse(status=200)

    data = event.get('data', {})
    reference = data.get('reference')

    if not reference:
        return HttpResponse(status=400)

    # Parcel and bus-hire payments carry their own references.
    from connect.paystack_extra import handle_extra_charge
    if handle_extra_charge(reference, data):
        return HttpResponse(status=200)

    refund_after_commit = False
    try:
        with transaction.atomic():
            payment = (
                Payment.objects
                .select_for_update()
                .select_related('booking__user')
                .get(provider_reference=reference)
            )

            booking = payment.booking

            # Paystack may retry the same webhook.
            # If we already processed it, do nothing.
            if payment.status in ('confirmed', 'refunded'):
                return HttpResponse(status=200)

            # This webhook is only for digital payments.
            if payment.method != 'digital':
                return HttpResponse(status=200)

            paystack_amount = data.get('amount')

            if paystack_amount is None:
                payment.status = 'failed'
                payment.save(update_fields=['status'])
                transaction.on_commit(
                    lambda: _alert_payment_problem(reference, 'amount missing in webhook')
                )
                return HttpResponse(status=200)

            expected_amount = int(
                payment.amount * Decimal('100')
            )

            try:
                paystack_amount = int(paystack_amount)
            except (TypeError, ValueError):
                payment.status = 'failed'
                payment.save(update_fields=['status'])
                transaction.on_commit(
                    lambda: _alert_payment_problem(reference, 'amount unreadable in webhook')
                )
                return HttpResponse(status=200)

            # Never trust the gateway response blindly.
            # The amount must match what CONNECT expected.
            if (
                paystack_amount != expected_amount
                or data.get('currency', 'KES') != 'KES'
            ):
                payment.status = 'failed'
                payment.save(update_fields=['status'])
                transaction.on_commit(
                    lambda: _alert_payment_problem(
                        reference,
                        f'amount/currency mismatch: paid {paystack_amount} '
                        f'{data.get("currency")}, expected {expected_amount}',
                    )
                )
                return HttpResponse(status=200)

            # -------------------------------------------------
            # PAYMENT CONFIRMED
            # -------------------------------------------------
            #
            # We deliberately do NOT add money to the user's
            # Django Wallet here.
            #
            # Paystack confirmation means the payment succeeded.
            # It does NOT mean CONNECT has released the money
            # to the transport company.
            #

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

            # If the trip has already departed by the time the
            # successful payment webhook arrives, the booking
            # cannot be used.
            dead_booking = booking.status in (
                'cancelled',
                'completed',
                'no_show',
            )

            if trip_has_departed(booking.trip) or dead_booking:
                # Money arrived for a booking that can no longer be used:
                # the trip is gone, or the booking was cancelled/expired and
                # its seat may already be resold. Refund it; never revive it.
                # The refund calls Paystack, so it runs AFTER this
                # transaction commits (see below).
                if booking.status in ('pending', 'confirmed'):
                    booking.status = 'cancelled'
                    booking.save(update_fields=['status'])
                refund_after_commit = True
            else:
                booking.status = 'confirmed'
                booking.save(update_fields=['status'])
                create_booking_hold(booking)

    except Payment.DoesNotExist:
        # Unknown references must not cause endless Paystack retries, but a
        # signed successful charge we cannot match is real money.
        _alert_payment_problem(reference, 'charge.success for an unknown reference')
        return HttpResponse(status=200)

    if refund_after_commit:
        try:
            settle_booking_fault(booking, fault_party='company')
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                'Refund for late payment %s failed; needs follow-up', reference)
            try:
                send_admin_alert_sms(
                    f'Late payment {reference} confirmed but refund failed. '
                    f'Check booking {booking.booking_number}.')
            except Exception:
                pass

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

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    event_type = event.get('event')
    new_refund_status = REFUND_EVENT_STATUS_MAP.get(event_type)

    if new_refund_status is None:
        # Not a refund event we care about.
        return HttpResponse(status=200)

    data = event.get('data', {})
    transaction_reference = data.get('transaction_reference')

    if not transaction_reference:
        return HttpResponse(status=400)

    try:
        with transaction.atomic():
            payment = (
                Payment.objects
                .select_for_update()
                .get(provider_reference=transaction_reference)
            )

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
                    send_admin_alert_sms(
                        f"Refund FAILED for booking "
                        f"{payment.booking.booking_number} "
                        f"(payment #{payment.id}, amount "
                        f"{payment.refund_amount}). "
                        f"Paystack could not process the reversal - "
                        f"needs manual follow-up."
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
            booking = (
                Booking.objects
                .select_for_update()
                .get(id=booking_id)
            )

            user = request.user

            # Cash payment confirmation is allowed for:
            # - Django superusers
            # - Company Managers for their own company
            # - Company Operators for their own company
            # - The driver assigned to this booking's trip
            #
            # Company Auditors are read-only.
            # Generic is_staff=True does not grant payment authority.
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
                return Response(
                    {
                        'error': (
                            'Unauthorized to confirm '
                            'cash payments.'
                        )
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

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

            if trip_has_departed(booking.trip):
                return Response(
                    {
                        'error': (
                            'This trip has already departed. '
                            'Payment can no longer be confirmed.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
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


# ============================================================
# CREATE BOOKING
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_booking(request):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
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
    pickup_stage_id = validated_data.get('pickup_stage_id')
    legacy_pickup_location = validated_data.get(
        'pickup_location',
        ''
    ).strip()

    try:
        with transaction.atomic():
            trip = (
                Trip.objects
                .select_for_update()
                .select_related('route')
                .get(id=trip_id)
            )

            if not (
                (
                    trip.status == 'scheduled'
                    and trip.departure_at > timezone.now()
                )
                or (
                    trip.status == 'boarding'
                    and trip.departure_at
                    > timezone.now() - _boarding_book_window()
                )
            ):
                return Response(
                    {
                        'error': (
                            'Cannot book trips that are not '
                            'scheduled or have already departed.'
                        )
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
            ).count() >= pending_cap:
                return Response(
                    {
                        'error': (
                            'You have too many unpaid bookings. Pay for or '
                            'cancel one before booking another.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            confirmed_bookings = trip.bookings.exclude(
                status='cancelled'
            )

            taken_seats = sum(
                b.seats for b in confirmed_bookings
            )

            available_seats = trip.capacity - taken_seats

            if seats > available_seats:
                return Response(
                    {
                        'error': (
                            'Not enough seats available. '
                            f'Only {available_seats} remaining.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            total_amount = (
                trip.route.price * Decimal(str(seats))
            )

            booking = Booking.objects.create(
                user=request.user,
                trip=trip,
                route=trip.route,
                driver=trip.driver,
                pickup_location=pickup_location,
                pickup_stage=pickup_stage,
                seats=seats,
                total_amount=total_amount,
                status='pending'
            )

        return Response(
            {
                'message': (
                    'Booking created successfully. '
                    'Proceed to payment.'
                ),
                'booking_id': booking.id,
                'booking_number': booking.booking_number,
                'total_amount': str(total_amount),
                'pickup_location': booking.pickup_location,
                'pickup_stage_id': (
                    booking.pickup_stage_id
                    if booking.pickup_stage_id
                    else None
                ),
            },
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

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_bookings(request):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    bookings = (
        Booking.objects
        .filter(user=request.user)
        .select_related(
            'trip__route__company',
            'trip__driver',
            'pickup_stage',
            'payment',
        )
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
            'verification_pin': b.verification_pin if b.status == 'confirmed' else None,
            'trip_id': trip.id if trip else None,
            'departure_at': trip.departure_at if trip else None,
            'trip_status': trip.status if trip else None,

            'company_name': (
                route.company.name
                if route and route.company
                else None
            ),

            'route_name': route.name if route else None,
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
            'driver_bus_number': (
                driver.bus_number
                if driver
                else None
            ),
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

    # Platform superuser can view bookings across all companies.
    if request.user.is_superuser or request.user.role == 'platform_admin':
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
        'user': b.user.username,
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
    )

    if (
        booking.user != user
        and not user.is_superuser
        and not is_company_staff
    ):
        return Response(
            {'error': 'Unauthorized'},
            status=status.HTTP_403_FORBIDDEN
        )

    data = {
        'booking_id': booking.id,
        'booking_number': booking.booking_number,
        'user': booking.user.username,
        'trip_id': booking.trip.id if booking.trip else None,
        'route_name': booking.route.name,
        'pickup_location': booking.pickup_location,
        'seats': booking.seats,
        'total_amount': str(booking.total_amount),
        'status': booking.status,
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
                    )
                )
            ):
                return Response(
                    {'error': 'Unauthorized'},
                    status=status.HTTP_403_FORBIDDEN
                )

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

            # Reserve the refund inside this transaction but do NOT call
            # Paystack here: a rollback after Paystack accepted the refund
            # would erase the reservation and allow a second refund.
            refund_amount, refund_claim = claim_booking_refund(
                booking,
                fault_party
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
            with transaction.atomic():
                restored = (
                    Booking.objects
                    .select_for_update()
                    .get(pk=booking_id)
                )
                if restored.status == 'cancelled':
                    restored.status = previous_status
                    restored.save(update_fields=['status'])
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

            try:
                replacement_trip = (
                    Trip.objects
                    .select_for_update()
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

            taken_seats = (
                replacement_trip.bookings
                .exclude(status='cancelled')
                .aggregate(total=Sum('seats'))
                .get('total')
                or 0
            )

            available_seats = (
                replacement_trip.capacity - taken_seats
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
        with transaction.atomic():
            restored = Booking.objects.select_for_update().get(pk=booking_pk)
            if restored.status == 'cancelled':
                restored.status = previous_status
                restored.save(update_fields=['status'])
            IncidentResolution.objects.filter(pk=resolution_pk).delete()
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
                .select_for_update()
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
                return Response(
                    {
                        'error': (
                            'Unauthorized: You cannot verify '
                            'boarding for this trip.'
                        )
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

            if booking.status != 'confirmed':
                return Response(
                    {
                        'error': (
                            'Cannot board booking with status: '
                            f'{booking.status}'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                payment = booking.payment
            except Payment.DoesNotExist:
                return Response(
                    {
                        'error': (
                            'No payment record for this booking.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if payment.status != 'confirmed':
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
            payment.save(
                update_fields=['settlement_status']
            )

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
                    'booking_id': booking.id
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
    )

    is_platform_admin = user.is_superuser

    if not (
        is_passenger
        or is_assigned_driver
        or is_company_staff
        or is_platform_admin
    ):
        return Response(
            {'error': 'Unauthorized'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if booking.status in ('cancelled', 'no_show', 'completed') and not is_platform_admin:
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
            booking.status != 'confirmed'
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
         and booking.status in ('pending', 'confirmed'))
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
            'pickup': pickup_payload,
            'departure_at': booking.trip.departure_at if booking.trip else None,
            'trip_status': booking.trip.status if booking.trip else None,
            'incident': _active_incident_payload(booking),

            'passenger': {
                'name': passenger_user.username,
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
                'bus_number': driver.bus_number if driver else None,
                'latitude': d_lat,
                'longitude': d_lng,
                'location_updated_at': (
                    driver.location_updated_at
                    if driver
                    else None
                ),
            },
            **location_freshness_for_booking(booking_id),
        },
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_passenger_location(request, booking_id):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    try:
        booking = Booking.objects.get(
            id=booking_id,
            user=request.user
        )
    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found'},
            status=status.HTTP_404_NOT_FOUND
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
        return (
            user.company_id is not None
            and user.company_id == company_id
        )

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
        return (
            user.company_id is not None
            and user.company_id == company_id
        )

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

    if not trip_id:
        return Response(
            {'error': 'trip_id is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        trip = Trip.objects.select_related(
            'route',
            'route__company',
            'driver',
        ).get(id=trip_id)
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

    if incident_type not in valid_types:
        return Response(
            {
                'error': 'Invalid incident_type.',
                'valid_types': sorted(valid_types),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not description or not str(description).strip():
        return Response(
            {'error': 'description is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

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
        description = str(description).strip()

        if not description:
            return Response(
                {'error': 'description cannot be empty.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
            "status": booking.status,
            "passenger": booking.user.username,
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
            'trip',
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

            'booking': {
                'status': booking.status,
                'created_at': booking.created_at,
                'updated_at': booking.updated_at,
                'verification_pin': (
                    booking.verification_pin
                    if booking.status == 'confirmed'
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
    from django.db.models import Sum
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
        taken = (
            trip.bookings
            .exclude(status='cancelled')
            .aggregate(total=Sum('seats'))
            .get('total')
            or 0
        )
        available = trip.capacity - taken
        if booking.seats <= available:
            result.append({
                'id': trip.id,
                'departure_at': trip.departure_at,
                'available_seats': available,
            })

    return Response(result, status=status.HTTP_200_OK)


def _boarding_book_window():
    """How long past its departure time a boarding trip stays bookable."""
    from .services import BOARDING_BOOKABLE_WINDOW
    return BOARDING_BOOKABLE_WINDOW


# ============================================================
# WALK-IN BOOKING AT THE FIRST STAGE
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def walk_in_booking(request, trip_id):
    """Operator/driver books and boards a cash passenger at the first stage.

    Leaves the same trail as a normal cash booking that is later boarded:
    booking completed, payment confirmed + settlement eligible, a
    BoardingEvent, and the passenger's boarded_count incremented.
    """
    from django.contrib.auth import get_user_model
    from django.db.models import F as _F, Sum
    from notifications import sms as _sms
    from users.phone import canonical_phone

    raw_seats = request.data.get('seats', 1)
    try:
        if isinstance(raw_seats, bool):
            raise ValueError
        seats = int(str(raw_seats).strip())
    except (TypeError, ValueError):
        return Response({'error': 'seats must be a whole number.'},
                        status=status.HTTP_400_BAD_REQUEST)
    if seats < 1 or seats > 20:
        return Response({'error': 'seats must be between 1 and 20.'},
                        status=status.HTTP_400_BAD_REQUEST)

    phone = canonical_phone(str(request.data.get('phone_number', '')).strip())
    if not phone:
        return Response({'error': 'A valid passenger phone_number is required.'},
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

        if trip.status != 'boarding' or trip_has_departed(trip):
            return Response(
                {'error': 'Walk-in booking is only available while the '
                          'trip is boarding.'},
                status=status.HTTP_409_CONFLICT)

        stage = (
            PickupStage.objects
            .filter(route_id=trip.route_id, is_active=True)
            .order_by('order', 'id').first()
        )
        if stage is None:
            return Response({'error': 'This route has no active first stage.'},
                            status=status.HTTP_400_BAD_REQUEST)

        taken = (
            trip.bookings.exclude(status='cancelled')
            .aggregate(total=Sum('seats'))['total'] or 0
        )
        available = trip.capacity - taken
        if seats > available:
            return Response(
                {'error': f'Not enough seats available. Only {available} remaining.'},
                status=status.HTTP_400_BAD_REQUEST)

        passenger = User.objects.filter(phone_number=phone).first()
        if passenger is None:
            base = f"walkin_{phone}".replace('+', '')
            username, n = base, 1
            while User.objects.filter(username=username).exists():
                n += 1
                username = f"{base}_{n}"
            passenger = User.objects.create_user(
                username=username, phone_number=phone, password=None)
        elif passenger.role != 'passenger' or passenger.is_superuser:
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
        'seats_remaining': available - seats,
    }, status=status.HTTP_201_CREATED)


from users.route_scope import (  # noqa: E402
    can_handle_route,
    operator_route_ids,
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
