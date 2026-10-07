from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from companies.models import Company
from drivers.models import Driver
from drivers.views import COMPANY_STAFF_ROLES
from users.permissions import can_manage_company

from .models import CharterRequest
from django.conf import settings

from connect import paystack_extra as paystack
from .services import (
    CharterError, cancel_charter, check_payable, complete_charter, create_charter,
    decline_charter, quote_charter, set_pending_reference,
)


class CharterCreateSerializer(serializers.Serializer):
    company_id = serializers.IntegerField(min_value=1)
    purpose = serializers.CharField(max_length=200)
    pickup_location = serializers.CharField(max_length=255)
    destination = serializers.CharField(max_length=255)
    depart_at = serializers.DateTimeField()
    return_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    passenger_count = serializers.IntegerField(min_value=1, max_value=200)
    contact_name = serializers.CharField(max_length=100)
    contact_phone = serializers.CharField(max_length=20)
    notes = serializers.CharField(max_length=1000, required=False, allow_blank=True, default='')


class QuoteSerializer(serializers.Serializer):
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=1)
    driver_id = serializers.IntegerField(min_value=1)
    valid_hours = serializers.IntegerField(min_value=1, max_value=168, default=48)


def _qs():
    return CharterRequest.objects.select_related('passenger', 'company', 'driver')


def _driver_for(user):
    if getattr(user, 'role', None) != 'driver' or not user.phone_number:
        return None
    return Driver.objects.filter(phone_number=user.phone_number).first()


def _is_staff(user):
    return (not user.is_superuser and user.role in COMPANY_STAFF_ROLES
            and user.company_id is not None)


def _visible(user, charter_id):
    charter = _qs().filter(id=charter_id).first()
    if charter is None:
        return None
    if user.is_superuser or charter.passenger_id == user.id:
        return charter
    driver = _driver_for(user)
    if (driver and charter.driver_id == driver.id
            and charter.status in ('confirmed', 'completed')):
        return charter
    if _is_staff(user) and user.company_id == charter.company_id:
        return charter
    return None


def payload(c, viewer):
    data = {
        'id': c.id,
        'reference': c.reference,
        'status': c.effective_status(),
        'company': c.company.name,
        'purpose': c.purpose,
        'pickup_location': c.pickup_location,
        'destination': c.destination,
        'depart_at': c.depart_at,
        'return_at': c.return_at,
        'passenger_count': c.passenger_count,
        'contact_name': c.contact_name,
        'contact_phone': c.contact_phone,
        'notes': c.notes,
        'quote_price': str(c.quote_price) if c.quote_price is not None else None,
        'quote_valid_until': c.quote_valid_until,
        'decline_reason': c.decline_reason,
        'paid_at': c.paid_at,
        'created_at': c.created_at,
    }
    if c.driver and c.status in ('confirmed', 'completed'):
        data['driver'] = {
            'name': c.driver.name,
            'phone_number': c.driver.phone_number,
            'bus_number': c.driver.bus_number,
        }
    if viewer.is_superuser or _is_staff(viewer):
        data['passenger_account'] = {
            'name': c.passenger.display_name,
            'phone_number': c.passenger.phone_number,
        }
    return data


def _call(fn, **kwargs):
    try:
        return fn(**kwargs), None
    except CharterRequest.DoesNotExist:
        return None, Response({'error': 'Request not found.'}, status=404)
    except CharterError as exc:
        return None, Response({'error': exc.message}, status=exc.status_code)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def charter_companies(request):
    rows = Company.objects.filter(accepts_charters=True).order_by('name').values('id', 'name')
    return Response(list(rows))


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def charter_list_create(request):
    if request.method == 'GET':
        rows = _qs().filter(passenger=request.user)[:100]
        return Response([payload(c, request.user) for c in rows])

    ser = CharterCreateSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=400)
    charter, err = _call(create_charter, passenger=request.user, **ser.validated_data)
    if err:
        return err
    return Response(payload(_qs().get(id=charter.id), request.user), status=201)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def charter_detail(request, charter_id):
    charter = _visible(request.user, charter_id)
    if charter is None:
        return Response({'error': 'Request not found.'}, status=404)
    return Response(payload(charter, request.user))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def charter_company(request):
    user = request.user
    if not (user.is_superuser or _is_staff(user)):
        return Response({'error': 'Staff access required.'}, status=403)
    qs = _qs()
    if not user.is_superuser:
        qs = qs.filter(company_id=user.company_id)
    wanted = request.query_params.get('status')
    if wanted in dict(CharterRequest.STATUS_CHOICES):
        qs = qs.filter(status=wanted)
    return Response([payload(c, user) for c in qs[:200]])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def driver_charters(request):
    driver = _driver_for(request.user)
    if driver is None:
        return Response({'error': 'Only drivers can do this.'}, status=403)
    rows = _qs().filter(driver=driver, status='confirmed')[:100]
    return Response([payload(c, request.user) for c in rows])


def _manager_target(request, charter_id):
    charter = _visible(request.user, charter_id)
    if charter is None:
        return None, Response({'error': 'Request not found.'}, status=404)
    if not can_manage_company(request.user, charter.company_id):
        return None, Response({'error': 'Only a company manager can do this.'}, status=403)
    return charter, None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def charter_quote(request, charter_id):
    charter, err = _manager_target(request, charter_id)
    if err:
        return err
    ser = QuoteSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=400)
    result, err = _call(quote_charter, charter_id=charter.id, manager=request.user,
                        price=ser.validated_data['price'],
                        driver_id=ser.validated_data['driver_id'],
                        valid_hours=ser.validated_data['valid_hours'])
    if err:
        return err
    return Response(payload(_qs().get(id=result.id), request.user))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def charter_decline(request, charter_id):
    charter, err = _manager_target(request, charter_id)
    if err:
        return err
    result, err = _call(decline_charter, charter_id=charter.id, manager=request.user,
                        reason=str(request.data.get('reason', '')))
    if err:
        return err
    return Response(payload(_qs().get(id=result.id), request.user))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def charter_cancel(request, charter_id):
    result, err = _call(cancel_charter, charter_id=charter_id, user=request.user)
    if err:
        return err
    return Response(payload(_qs().get(id=result.id), request.user))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def charter_complete(request, charter_id):
    charter = _visible(request.user, charter_id)
    if charter is None:
        return Response({'error': 'Request not found.'}, status=404)
    driver = _driver_for(request.user)
    assigned = driver is not None and charter.driver_id == driver.id
    if not (assigned or can_manage_company(request.user, charter.company_id)):
        return Response({'error': 'Only the assigned driver or a manager can do this.'}, status=403)
    result, err = _call(complete_charter, charter_id=charter.id)
    if err:
        return err
    return Response(payload(_qs().get(id=result.id), request.user))


def _frontend(path):
    return f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').rstrip('/')}{path}"


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def charter_pay(request, charter_id):
    charter, err = _call(check_payable, charter_id=charter_id, user=request.user)
    if err:
        return err
    reference = paystack.new_reference('CHT', charter.id)
    try:
        url = paystack.initialize(
            email=request.user.email or f'user_{request.user.id}@connect.local',
            amount=charter.quote_price,
            reference=reference,
            callback_url=_frontend(f'/passenger/charter/{charter.id}'),
            metadata={'charter_id': charter.id, 'user_id': request.user.id},
        )
    except paystack.GatewayError as exc:
        return Response({'error': exc.message}, status=exc.status_code)
    set_pending_reference(charter_id=charter.id, reference=reference)
    return Response({'authorization_url': url, 'reference': reference})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def charter_verify(request, charter_id):
    charter = _qs().filter(id=charter_id, passenger=request.user).first()
    if charter is None:
        return Response({'error': 'Request not found.'}, status=404)
    if charter.status != 'quoted':
        return Response(payload(charter, request.user))

    reference = charter.provider_reference or ''
    if not paystack.CHARTER_REF.match(reference):
        return Response({'error': 'Start a payment first.'}, status=409)
    try:
        data = paystack.verify(reference)
    except paystack.GatewayError as exc:
        return Response({'error': exc.message}, status=exc.status_code)
    if data.get('status') != 'success':
        return Response({'status': charter.effective_status(), 'message': 'Payment has not completed yet.'}, status=202)
    try:
        paystack.apply_charge(reference, data)
    except (CharterError, paystack.GatewayError) as exc:
        return Response({'error': exc.message}, status=exc.status_code)
    return Response(payload(_qs().get(id=charter.id), request.user))


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def charter_settings(request):
    user = request.user
    if user.is_superuser or user.role != 'company_manager' or user.company_id is None:
        return Response({'error': 'Company manager access required.'}, status=403)
    company = Company.objects.get(id=user.company_id)
    if request.method == 'PATCH':
        value = request.data.get('accepts_charters')
        if not isinstance(value, bool):
            return Response({'error': 'accepts_charters must be true or false.'}, status=400)
        company.accepts_charters = value
        company.save(update_fields=['accepts_charters'])
    return Response({'accepts_charters': company.accepts_charters})
