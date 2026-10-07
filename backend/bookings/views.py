from django.db.models import Q
import hmac
import hashlib
import json
import requests

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

from .models import Booking, Payment, BoardingEvent
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

    if booking.status == 'cancelled':
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

    existing_payment = Payment.objects.filter(
        booking=booking
    ).first()

    if existing_payment and existing_payment.status == 'confirmed':
        return Response(
            {'error': 'This booking has already been paid for'},
            status=status.HTTP_400_BAD_REQUEST
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
        'callback_url': request.data.get(
            'callback_url',
            f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')}/passenger/payment/{booking.id}"
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
            {'error': 'Unable to connect to payment gateway'},
            status=status.HTTP_502_BAD_GATEWAY
        )

    if response.status_code != 200:
        return Response(
            {'error': 'Failed to initialize payment gateway'},
            status=status.HTTP_502_BAD_GATEWAY
        )

    try:
        res_data = response.json()
    except ValueError:
        return Response(
            {'error': 'Invalid response from payment gateway'},
            status=status.HTTP_502_BAD_GATEWAY
        )

    if not res_data.get('status'):
        return Response(
            {
                'error': res_data.get(
                    'message',
                    'Payment initialization error'
                )
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    data = res_data['data']

    Payment.objects.update_or_create(
        booking=booking,
        defaults={
            'provider_reference': data['reference'],
            'amount': booking.total_amount,
            'method': 'digital',
            'status': 'pending'
        }
    )

    return Response(
        {
            'authorization_url': data['authorization_url'],
            'reference': data['reference']
        },
        status=status.HTTP_200_OK
    )


# ============================================================
# PAYSTACK M-PESA CHARGE
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def initialize_mpesa_payment(request, booking_id):
    """Send a Paystack M-PESA STK push to the passenger's saved phone."""
    try:
        booking = Booking.objects.select_related('user', 'trip').get(
            id=booking_id,
            user=request.user,
        )
    except Booking.DoesNotExist:
        return Response({'error': 'Booking not found'}, status=404)

    if booking.status in ('cancelled', 'completed', 'no_show'):
        return Response({'error': 'This booking cannot be paid for.'}, status=400)

    if trip_has_departed(booking.trip):
        return Response({'error': 'This trip has already departed.'}, status=400)

    phone = request.data.get('phone_number') or booking.user.phone_number
    if not phone:
        return Response(
            {'error': 'Enter an M-PESA phone number.'},
            status=400,
        )

    phone = str(phone).strip()
    if not phone.startswith('+254') or len(phone) != 13 or not phone[1:].isdigit():
        return Response(
            {'error': 'Enter a valid Kenyan phone number, e.g. +254710000000.'},
            status=400,
        )

    existing = Payment.objects.filter(booking=booking).first()
    if existing and existing.status == 'confirmed':
        return Response({'error': 'This booking has already been paid for.'}, status=400)

    # A new M-PESA charge replaces an abandoned pending digital attempt.
    amount_in_cents = int(booking.total_amount * Decimal('100'))
    headers = {
        'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'email': request.user.email or f'user_{request.user.id}@connect.local',
        'amount': amount_in_cents,
        'currency': 'KES',
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
            {'error': 'Unable to connect to Paystack.'},
            status=502,
        )

    try:
        result = gateway_response.json()
    except ValueError:
        return Response({'error': 'Invalid response from Paystack.'}, status=502)

    if gateway_response.status_code != 200 or not result.get('status'):
        return Response(
            {'error': result.get('message', 'Unable to start M-PESA payment.')},
            status=400,
        )

    data = result.get('data') or {}
    reference = data.get('reference')
    if not reference:
        return Response({'error': 'Paystack did not return a payment reference.'}, status=502)

    Payment.objects.update_or_create(
        booking=booking,
        defaults={
            'provider_reference': reference,
            'amount': booking.total_amount,
            'method': 'digital',
            'status': 'pending',
            'settlement_status': 'not_ready',
        },
    )

    return Response(
        {
            'booking_id': booking.id,
            'reference': reference,
            'status': data.get('status', 'pay_offline'),
            'display_text': data.get(
                'display_text',
                'Please check your phone and complete the M-PESA authorization.',
            ),
            'phone': phone,
            'amount': str(booking.total_amount),
        },
        status=200,
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

    if booking.status not in (
        'cancelled',
        'completed',
        'no_show',
    ):
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
            gateway_response.status_code == 200
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
        return Response({'payment_status': payment.status, 'booking_status': payment.booking.status})

    return Response({
        'payment_status': data.get('status', payment.status),
        'message': data.get('gateway_response') or data.get('message') or 'Payment is still pending.',
    })


# ============================================================
# PAYSTACK WEBHOOK
# ============================================================

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

    if not hmac.compare_digest(signature, computed_signature):
        return HttpResponse(status=400)

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

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
            if payment.status == 'confirmed':
                return HttpResponse(status=200)

            # This webhook is only for digital payments.
            if payment.method != 'digital':
                return HttpResponse(status=200)

            paystack_amount = data.get('amount')

            if paystack_amount is None:
                payment.status = 'failed'
                payment.save(update_fields=['status'])
                return HttpResponse(status=200)

            expected_amount = int(
                payment.amount * Decimal('100')
            )

            try:
                paystack_amount = int(paystack_amount)
            except (TypeError, ValueError):
                payment.status = 'failed'
                payment.save(update_fields=['status'])
                return HttpResponse(status=200)

            # Never trust the gateway response blindly.
            # The amount must match what CONNECT expected.
            if paystack_amount != expected_amount:
                payment.status = 'failed'
                payment.save(update_fields=['status'])
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
            if trip_has_departed(booking.trip):
                try:
                    settle_booking_fault(
                        booking,
                        fault_party='company'
                    )
                except ValueError:
                    # Refund request failed at the provider level.
                    # Keep payment.status as confirmed so this is
                    # visible for manual follow-up.
                    pass

                booking.status = 'cancelled'
                booking.save(update_fields=['status'])
            else:
                booking.status = 'confirmed'
                booking.save(update_fields=['status'])
                create_booking_hold(booking)

    except Payment.DoesNotExist:
        # Unknown references should not cause repeated Paystack
        # webhook retries.
        return HttpResponse(status=200)

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

    if not hmac.compare_digest(signature, computed_signature):
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

            # A refund already marked processed is final.
            if payment.refund_status == 'processed':
                return HttpResponse(status=200)

            update_fields = ['refund_status']
            payment.refund_status = new_refund_status

            refund_reference = data.get('refund_reference')

            if refund_reference and not payment.refund_reference:
                payment.refund_reference = str(refund_reference)
                update_fields.append('refund_reference')

            if new_refund_status == 'processed':
                # Money genuinely reached the passenger.
                payment.status = 'refunded'
                payment.refunded_at = timezone.now()

                update_fields += [
                    'status',
                    'refunded_at',
                ]

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

    if booking.status in ('cancelled', 'completed', 'no_show'):
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

    existing = Payment.objects.filter(booking=booking).first()

    if existing and existing.status == 'confirmed':
        return Response(
            {'error': 'This booking has already been paid for'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if (
        existing
        and existing.method == 'digital'
        and existing.status == 'pending'
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

    payment, _ = Payment.objects.update_or_create(
        booking=booking,
        defaults={
            'amount': booking.total_amount,
            'method': 'cash',
            'status': 'pending',
            'provider_reference': None,
        }
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
                )
            )

            # Driver assigned to this trip may confirm
            # the cash payment.
            if (
                not is_authorized
                and booking.trip
                and booking.trip.driver
            ):
                if booking.trip.driver.phone_number == getattr(
                    user,
                    'phone_number',
                    None
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

            if (
                trip.status != 'scheduled'
                or trip.departure_at <= timezone.now()
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
            'trip_id': trip.id if trip else None,
            'departure_at': trip.departure_at if trip else None,

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
            .select_related('trip', 'route__company')
            .get(id=booking_id)
        )
    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Driver assignment is allowed for:
    # - Django superusers
    # - Company Managers for their own company
    # - Company Operators for their own company
    #
    # Company Auditors are read-only and cannot assign drivers.
    user = request.user

    is_allowed = (
        user.is_superuser
        or (
            user.role in {
                'company_manager',
                'company_operator',
            }
            and user.company_id == booking.route.company_id
        )
    )

    if not is_allowed:
        return Response(
            {'error': 'Manager or Operator authorization required'},
            status=status.HTTP_403_FORBIDDEN
        )

    serializer = AssignDriverSerializer(
        data=request.data
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        driver = Driver.objects.get(
            id=serializer.validated_data['driver_id']
        )
    except Driver.DoesNotExist:
        return Response(
            {'error': 'Driver not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    if driver.company_id != booking.route.company_id:
        return Response(
            {'error': 'Driver must belong to the same company as the booking.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    with transaction.atomic():
        trip = booking.trip
        trip.driver = driver
        trip.save(update_fields=['driver'])

        booking.driver = driver
        booking.save(update_fields=['driver'])

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
            # Lock only the Booking row.
            # Do not select_related() while using
            # select_for_update() because Booking.trip
            # may be nullable on PostgreSQL.
            booking = (
                Booking.objects
                .select_for_update()
                .get(id=booking_id)
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

            refund_amount = settle_booking_fault(
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

    return Response(
        {
            'message': 'Booking cancelled successfully.',
            'fault_party': fault_party,
            'refund_amount': str(refund_amount),
        },
        status=status.HTTP_200_OK
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resolve_incident_booking(request, booking_id):
    """
    Let an incident-affected passenger choose refund or reschedule.

    Rescheduling keeps the existing booking and payment. It does not
    create a second payment or a second booking.
    """
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
                refund_amount = settle_booking_fault(
                    booking,
                    fault_party='company',
                )

                booking.status = 'cancelled'
                booking.save(update_fields=['status'])

                IncidentResolution.objects.create(
                    booking=booking,
                    incident=incident,
                    resolution='refund',
                    status='completed',
                    refund_amount=refund_amount,
                    completed_at=timezone.now(),
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
            # IMPORTANT:
            # Lock only the Booking row.
            # Booking.trip is nullable, so using select_related()
            # together with select_for_update() can fail on
            # PostgreSQL because of the generated outer join.
            booking = (
                Booking.objects
                .select_for_update()
                .get(id=booking_id)
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
                )
            )

            if (
                not is_authorized
                and booking.trip
                and booking.trip.driver
                and booking.trip.driver.phone_number
                and getattr(user, 'phone_number', None)
                and (
                    booking.trip.driver.phone_number
                    == user.phone_number
                )
            ):
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
                if str(qr_data) != str(
                    booking.booking_number
                ):
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
                if (
                    str(
                        getattr(
                            booking,
                            'verification_pin',
                            ''
                        )
                    )
                    != str(boarding_pin)
                ):
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
            booking.user.boarded_count += 1
            booking.user.save(
                update_fields=['boarded_count']
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
        and booking.driver.phone_number == user.phone_number
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
            and incident.trip.driver.phone_number == user.phone_number
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
            and trip.driver.phone_number == user.phone_number
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
            trip__driver__phone_number=user.phone_number
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
            and user.phone_number == driver.phone_number
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
        .filter(status="boarding")
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
            "verification_pin": (
                booking.verification_pin
                if booking.status == "confirmed"
                else None
            ),

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
        or (user.role == 'driver' and user.phone_number == driver.phone_number)
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
            departure_at__gte=timezone.now() - _dt.timedelta(hours=12),
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

    from bookings.services import settle_unboarded_no_shows

    with transaction.atomic():
        trip = Trip.objects.select_for_update().get(pk=trip.pk)
        settled, protected = settle_unboarded_no_shows(trip)
        trip.status = 'completed'
        trip.save(update_fields=['status'])

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
