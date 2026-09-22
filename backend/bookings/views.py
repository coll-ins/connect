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

from companies.models import Trip
from users.permissions import can_manage_company
from notifications.sms import send_admin_alert_sms
from drivers.models import Driver
from wallets.models import Wallet, WalletTransaction

from .models import Booking, Payment, BoardingEvent
from .services import settle_booking_fault, trip_has_departed
from .serializers import (
    BookingCreateSerializer,
    AssignDriverSerializer,
    PassengerLocationSerializer,
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
            'http://localhost:5500/payment-success.html'
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
            is_authorized = user.is_staff or user.is_superuser

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
def create_booking(request):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    serializer = BookingCreateSerializer(
        data=request.data
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    validated_data = serializer.validated_data
    trip_id = validated_data['trip_id']
    seats = validated_data['seats']
    pickup_location = validated_data['pickup_location']

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
                'total_amount': str(total_amount)
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
def get_my_bookings(request):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    bookings = (
        Booking.objects
        .filter(user=request.user)
        .select_related('trip__route', 'payment')
    )

    data = [{
        'booking_id': b.id,
        'booking_number': b.booking_number,
        'trip_id': b.trip.id if b.trip else None,
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

    return Response(data, status=status.HTTP_200_OK)


@api_view(['GET'])
def get_all_bookings(request):
    if (
        not request.user.is_authenticated
        or not request.user.is_staff
    ):
        return Response(
            {'error': 'Admin authorization required'},
            status=status.HTTP_403_FORBIDDEN
        )

    bookings = (
        Booking.objects
        .all()
        .select_related('user', 'trip__route', 'payment')
    )

    data = [{
        'booking_id': b.id,
        'booking_number': b.booking_number,
        'user': b.user.username,
        'trip_id': b.trip.id if b.trip else None,
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
        'created_at': b.created_at,
    } for b in bookings]

    return Response(data, status=status.HTTP_200_OK)


@api_view(['GET'])
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

    if booking.user != request.user and not request.user.is_staff:
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

    # is_staff kept for backward compatibility (existing admin
    # accounts), company_admin/platform_admin via the shared helper
    # for everyone else — either grants access, but a company_admin
    # only for their own company's bookings.
    if not (request.user.is_staff or can_manage_company(request.user, booking.route.company)):
        return Response(
            {'error': 'Admin authorization required'},
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
def cancel_booking(request, booking_id):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    is_admin_or_staff = (
        request.user.is_staff
        or request.user.is_superuser
    )

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
                booking.user != request.user
                and not is_admin_or_staff
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

            if (
                fault_party == 'company'
                and not is_admin_or_staff
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

            # Staff/admin can verify boarding.
            # Drivers can verify boarding when their phone matches
            # the assigned trip driver.
            is_authorized = (
                user.is_staff
                or user.is_superuser
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

@api_view(['POST'])
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
def set_stage_departure(request, booking_id):
    if (
        not request.user.is_authenticated
        or not request.user.is_staff
    ):
        return Response(
            {'error': 'Staff authorization required'},
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

    try:
        booking = Booking.objects.get(
            id=booking_id
        )
    except Booking.DoesNotExist:
        return Response(
            {'error': 'Booking not found'},
            status=status.HTTP_404_NOT_FOUND
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


@api_view(['GET'])
def get_driver_bookings(request, driver_id):
    if (
        not request.user.is_authenticated
        or not request.user.is_staff
    ):
        return Response(
            {'error': 'Staff authorization required'},
            status=status.HTTP_403_FORBIDDEN
        )

    bookings = (
        Booking.objects
        .filter(
            driver_id=driver_id,
            status__in=['pending', 'confirmed']
        )
        .select_related(
            'user',
            'route',
            'trip'
        )
    )

    data = [{
        'booking_id': b.id,
        'booking_number': b.booking_number,
        'passenger': b.user.username,
        'route': b.route.name,
        'seats': b.seats,
        'status': b.status
    } for b in bookings]

    return Response(
        data,
        status=status.HTTP_200_OK
    )
