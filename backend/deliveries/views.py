import re

from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from companies.models import PickupStage, Trip
from drivers.models import Driver
from drivers.views import COMPANY_STAFF_ROLES

from .models import Parcel
from django.conf import settings

from connect import paystack_extra as paystack
from .services import ParcelError, cancel_parcel, create_parcel, deliver, pick_up


class ParcelCreateSerializer(serializers.Serializer):
    trip_id = serializers.IntegerField(min_value=1)
    pickup_stage_id = serializers.IntegerField(min_value=1)
    dropoff_stage_id = serializers.IntegerField(min_value=1)
    size = serializers.ChoiceField(choices=[c[0] for c in Parcel.SIZE_CHOICES])
    description = serializers.CharField(max_length=200)
    receiver_name = serializers.CharField(max_length=100)
    receiver_phone = serializers.CharField(max_length=20)
    no_prohibited_items = serializers.BooleanField()

    def validate_no_prohibited_items(self, value):
        if value is not True:
            raise serializers.ValidationError(
                'You must confirm the parcel contains no prohibited items.'
            )
        return value


def _qs():
    return Parcel.objects.select_related(
        'sender', 'trip__route__company', 'pickup_stage', 'dropoff_stage'
    )


def _driver_for(user):
    if getattr(user, 'role', None) != 'driver' or not user.phone_number:
        return None
    return Driver.objects.filter(phone_number=user.phone_number).first()


def _is_staff(user):
    return (
        not user.is_superuser
        and user.role in COMPANY_STAFF_ROLES
        and user.company_id is not None
    )


def _visible(user, parcel_id):
    parcel = _qs().filter(id=parcel_id).first()
    if parcel is None:
        return None
    if user.is_superuser or parcel.sender_id == user.id:
        return parcel
    driver = _driver_for(user)
    if driver and parcel.trip.driver_id == driver.id:
        return parcel
    if _is_staff(user) and user.company_id == parcel.trip.route.company_id:
        return parcel
    return None


def payload(parcel, viewer):
    trip = parcel.trip
    is_sender = viewer.id == parcel.sender_id
    data = {
        'id': parcel.id,
        'tracking_code': parcel.tracking_code,
        'status': parcel.status,
        'size': parcel.size,
        'description': parcel.description,
        'price': str(parcel.price),
        'company': trip.route.company.name,
        'route': trip.route.name,
        'trip_id': trip.id,
        'departure_at': trip.departure_at,
        'pickup_stage': {'id': parcel.pickup_stage_id, 'name': parcel.pickup_stage.name},
        'dropoff_stage': {'id': parcel.dropoff_stage_id, 'name': parcel.dropoff_stage.name},
        'receiver_name': parcel.receiver_name,
        'receiver_phone': parcel.receiver_phone,
        'paid_at': parcel.paid_at,
        'picked_up_at': parcel.picked_up_at,
        'delivered_at': parcel.delivered_at,
        'created_at': parcel.created_at,
    }
    if not is_sender:
        data['sender_name'] = parcel.sender.display_name
        data['sender_phone'] = parcel.sender.phone_number
    if is_sender and parcel.status in ('pending_payment', 'paid', 'picked_up'):
        data['handover_pin'] = parcel.handover_pin
    return data


def _call(fn, **kwargs):
    try:
        return fn(**kwargs), None
    except Parcel.DoesNotExist:
        return None, Response({'error': 'Parcel not found.'}, status=404)
    except ParcelError as exc:
        return None, Response({'error': exc.message}, status=exc.status_code)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def parcel_list_create(request):
    if request.method == 'GET':
        parcels = _qs().filter(sender=request.user)[:100]
        return Response([payload(p, request.user) for p in parcels])

    ser = ParcelCreateSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=400)
    data = dict(ser.validated_data)
    data.pop('no_prohibited_items')

    parcel, err = _call(create_parcel, sender=request.user, **data)
    if err:
        return err
    parcel = _qs().get(id=parcel.id)
    return Response(payload(parcel, request.user), status=201)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def parcel_quote(request):
    trip_id = request.query_params.get('trip_id', '')
    if not trip_id.isdigit():
        return Response({'error': 'trip_id is required.'}, status=400)
    trip = (
        Trip.objects.select_related('route')
        .filter(id=trip_id, status='scheduled', departure_at__gt=timezone.now())
        .first()
    )
    if trip is None:
        return Response({'error': 'Trip not found.'}, status=404)
    rates = {}
    for size, _ in Parcel.SIZE_CHOICES:
        rate = trip.route.parcel_rate(size)
        if rate:
            rates[size] = str(rate)
    stages = PickupStage.objects.filter(route=trip.route, is_active=True).values('id', 'name', 'order')
    return Response({'trip_id': trip.id, 'rates': rates, 'stages': list(stages)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def parcel_detail(request, parcel_id):
    parcel = _visible(request.user, parcel_id)
    if parcel is None:
        return Response({'error': 'Parcel not found.'}, status=404)
    return Response(payload(parcel, request.user))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def parcel_cancel(request, parcel_id):
    parcel, err = _call(cancel_parcel, parcel_id=parcel_id, user=request.user)
    if err:
        return err
    return Response(payload(_qs().get(id=parcel.id), request.user))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def parcel_pickup(request, parcel_id):
    driver = _driver_for(request.user)
    if driver is None:
        return Response({'error': 'Only drivers can do this.'}, status=403)
    parcel, err = _call(pick_up, parcel_id=parcel_id, driver=driver)
    if err:
        return err
    return Response(payload(_qs().get(id=parcel.id), request.user))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def parcel_deliver(request, parcel_id):
    driver = _driver_for(request.user)
    if driver is None:
        return Response({'error': 'Only drivers can do this.'}, status=403)
    pin = str(request.data.get('pin', '')).strip()
    if not re.fullmatch(r'\d{6}', pin):
        return Response({'error': 'Enter the 6-digit PIN.'}, status=400)
    parcel, err = _call(deliver, parcel_id=parcel_id, driver=driver, pin=pin)
    if err:
        return err
    return Response(payload(_qs().get(id=parcel.id), request.user))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def driver_parcels(request):
    driver = _driver_for(request.user)
    if driver is None:
        return Response({'error': 'Only drivers can do this.'}, status=403)
    parcels = _qs().filter(trip__driver=driver, status__in=['paid', 'picked_up'])[:200]
    return Response([payload(p, request.user) for p in parcels])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def company_parcels(request):
    user = request.user
    if not (user.is_superuser or _is_staff(user)):
        return Response({'error': 'Staff access required.'}, status=403)
    qs = _qs()
    if not user.is_superuser:
        qs = qs.filter(trip__route__company_id=user.company_id)
    wanted = request.query_params.get('status')
    if wanted in dict(Parcel.STATUS_CHOICES):
        qs = qs.filter(status=wanted)
    return Response([payload(p, user) for p in qs[:200]])


def _frontend(path):
    return f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').rstrip('/')}{path}"


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def parcel_pay(request, parcel_id):
    parcel = _qs().filter(id=parcel_id, sender=request.user).first()
    if parcel is None:
        return Response({'error': 'Parcel not found.'}, status=404)
    if parcel.status != 'pending_payment':
        return Response({'error': 'This parcel is not awaiting payment.'}, status=409)
    trip = parcel.trip
    if trip.status != 'scheduled' or trip.departure_at <= timezone.now():
        return Response({'error': 'This trip is no longer available.'}, status=409)

    reference = paystack.new_reference('PCL', parcel.id)
    try:
        url = paystack.initialize(
            email=request.user.email or f'user_{request.user.id}@connect.local',
            amount=parcel.price,
            reference=reference,
            callback_url=_frontend(f'/passenger/delivery/{parcel.id}'),
            metadata={'parcel_id': parcel.id, 'user_id': request.user.id},
        )
    except paystack.GatewayError as exc:
        return Response({'error': exc.message}, status=exc.status_code)
    Parcel.objects.filter(id=parcel.id, status='pending_payment').update(provider_reference=reference)
    return Response({'authorization_url': url, 'reference': reference})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def parcel_verify(request, parcel_id):
    parcel = _qs().filter(id=parcel_id, sender=request.user).first()
    if parcel is None:
        return Response({'error': 'Parcel not found.'}, status=404)
    if parcel.status != 'pending_payment':
        return Response(payload(parcel, request.user))

    reference = parcel.provider_reference or ''
    if not paystack.PARCEL_REF.match(reference):
        return Response({'error': 'Start a payment first.'}, status=409)
    try:
        data = paystack.verify(reference)
    except paystack.GatewayError as exc:
        return Response({'error': exc.message}, status=exc.status_code)
    if data.get('status') != 'success':
        return Response({'status': parcel.status, 'message': 'Payment has not completed yet.'}, status=202)
    try:
        paystack.apply_charge(reference, data)
    except (ParcelError, paystack.GatewayError) as exc:
        return Response({'error': exc.message}, status=exc.status_code)
    return Response(payload(_qs().get(id=parcel.id), request.user))
