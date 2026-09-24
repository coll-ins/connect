from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated

from companies.models import Company
from users.permissions import can_manage_company
from .models import Driver
from .serializers import DriverSerializer


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def driver_list(request):
    if request.method == 'GET':
        company_id = request.query_params.get('company_id')
        queryset = Driver.objects.select_related('company').all().order_by('id')
        if company_id:
            queryset = queryset.filter(company_id=company_id)
        return Response(DriverSerializer(queryset, many=True).data)

    if not request.user.is_authenticated:
        return Response({'error': 'Login required to add a driver.'}, status=401)

    company = get_object_or_404(Company, id=request.data.get('company'))
    if not can_manage_company(request.user, company):
        return Response(
            {'error': 'You are not authorized to add drivers for this company.'},
            status=403,
        )

    serializer = DriverSerializer(data=request.data)
    if serializer.is_valid():
        driver = serializer.save()
        return Response(DriverSerializer(driver).data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([AllowAny])
def driver_detail(request, driver_id):
    driver = get_object_or_404(
        Driver.objects.select_related('company'), id=driver_id
    )
    return Response(DriverSerializer(driver).data)


def _can_manage_driver(request, driver):
    user = request.user
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    if user.role == 'driver' and user.phone_number == driver.phone_number:
        return True
    return can_manage_company(user, driver.company)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def driver_location(request, driver_id):
    driver = get_object_or_404(Driver, id=driver_id)

    if not _can_manage_driver(request, driver):
        return Response({'error': 'Not authorized for this driver.'}, status=403)

    if request.method == 'GET':
        return Response(
            {
                'driver_id': driver.id,
                'name': driver.name,
                'latitude': driver.latitude,
                'longitude': driver.longitude,
                'location_updated_at': driver.location_updated_at,
            }
        )

    latitude = request.data.get('latitude')
    longitude = request.data.get('longitude')
    if latitude is None or longitude is None:
        return Response(
            {'error': 'latitude and longitude are required.'},
            status=400,
        )

    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return Response({'error': 'Invalid coordinates.'}, status=400)

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return Response({'error': 'Coordinates are out of range.'}, status=400)

    driver.latitude = latitude
    driver.longitude = longitude
    driver.save(update_fields=['latitude', 'longitude', 'location_updated_at'])

    return Response(
        {
            'message': 'Driver location updated.',
            'driver_id': driver.id,
            'latitude': driver.latitude,
            'longitude': driver.longitude,
            'location_updated_at': driver.location_updated_at,
        }
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_driver_profile(request):
    if request.user.role != 'driver' and not (request.user.is_staff or request.user.is_superuser):
        return Response({'error': 'Driver account required.'}, status=403)

    driver = Driver.objects.select_related('company').filter(
        phone_number=request.user.phone_number
    ).first()
    if not driver:
        return Response({'error': 'No driver profile is linked to this account.'}, status=404)
    return Response(DriverSerializer(driver).data)
