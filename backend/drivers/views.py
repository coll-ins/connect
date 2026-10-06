from django.db import transaction
from django.shortcuts import get_object_or_404

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated

from companies.models import Company
from users.models import CustomUser
from users.permissions import (
    can_manage_company,
    can_access_company,
)
from .models import Driver
from .serializers import DriverSerializer
from rest_framework.decorators import throttle_classes
from .throttles import DriverLocationThrottle
from django.utils import timezone


COMPANY_STAFF_ROLES = {
    'company_manager',
    'company_auditor',
    'company_operator',
}


def _is_company_staff(user):
    return (
        user
        and user.is_authenticated
        and not user.is_superuser
        and user.role in COMPANY_STAFF_ROLES
    )


def _can_view_driver(user, driver):
    """
    Check whether a user may view a specific driver.

    Superusers can view every driver.
    Company staff can view drivers only in their company.
    Other authenticated/public users may view driver details.
    """
    if not user or not user.is_authenticated:
        return True

    if user.is_superuser:
        return True

    if _is_company_staff(user):
        return (
            user.company_id is not None
            and user.company_id == driver.company_id
        )

    return True


def _can_manage_driver(user, driver):
    """
    Check whether a user may modify or delete a driver.

    Superusers:
        Global access.

    Company Managers:
        May manage drivers belonging to their company.

    Auditors/Operators:
        Read-only.

    Drivers:
        Cannot modify driver records through this endpoint.
        They use their own location endpoint instead.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return can_manage_company(user, driver.company)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def driver_list(request):
    """
    GET:
        Public driver listing, optionally filtered by company_id.

        Company staff are restricted to their own company.

    POST:
        Only Company Managers or superusers may create a driver.
    """
    if request.method == 'GET':
        company_id = request.query_params.get('company_id')

        queryset = Driver.objects.select_related(
            'company'
        ).all().order_by('id')

        if request.user.is_authenticated and not request.user.is_superuser:
            if _is_company_staff(request.user):
                if request.user.company_id is None:
                    return Response(
                        {'error': 'Company assignment required.'},
                        status=status.HTTP_403_FORBIDDEN,
                    )

                if (
                    company_id
                    and str(company_id) != str(request.user.company_id)
                ):
                    return Response(
                        {
                            'error':
                            'You cannot access drivers from another company.'
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )

                queryset = queryset.filter(
                    company_id=request.user.company_id
                )

            elif company_id:
                queryset = queryset.filter(
                    company_id=company_id
                )

        elif company_id:
            queryset = queryset.filter(
                company_id=company_id
            )

        return Response(
            DriverSerializer(queryset, many=True).data,
            status=status.HTTP_200_OK,
        )

    # POST — driver creation
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required to add a driver.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    # Company assignment is controlled by the server.
    #
    # Platform admin / superuser:
    #     may choose the company from the submitted company field.
    #
    # Company manager:
    #     must use the company attached to the authenticated account.
    #     Any submitted company value is deliberately ignored.
    if request.user.is_superuser:
        requested_company_id = request.data.get('company')

        if not requested_company_id:
            return Response(
                {'error': 'company is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        company = get_object_or_404(
            Company,
            id=requested_company_id,
        )
    else:
        if request.user.role != 'company_manager':
            return Response(
                {
                    'error':
                    'Only a Company Manager can add drivers.'
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.user.company_id is None:
            return Response(
                {'error': 'Company assignment required.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        company = get_object_or_404(
            Company,
            id=request.user.company_id,
        )

    # Authorization must happen before credential validation.
    if not can_manage_company(request.user, company):
        return Response(
            {
                'error':
                'Only a Company Manager can add drivers '
                'for their company.'
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = DriverSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

    phone_number = str(request.data.get('phone_number', '')).strip()
    password = request.data.get('password')

    if not phone_number:
        return Response(
            {'error': 'phone_number is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not password:
        return Response(
            {'error': 'password is required when creating a driver.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if len(password) < 6:
        return Response(
            {'error': 'Password must be at least 6 characters.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if Driver.objects.filter(phone_number=phone_number).exists():
        return Response(
            {'error': 'That phone number is already assigned to a driver.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if CustomUser.objects.filter(phone_number=phone_number).exists():
        return Response(
            {'error': 'That phone number is already linked to a user.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # The driver login uses phone_number + password.
    # Generate an internal Django username automatically.
    username_base = (
        f"driver_{phone_number}"
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
    )

    username = username_base
    suffix = 1

    while CustomUser.objects.filter(username=username).exists():
        suffix += 1
        username = f"{username_base}_{suffix}"

    with transaction.atomic():
        driver = serializer.save(company=company)

        CustomUser.objects.create_user(
            username=username,
            phone_number=phone_number,
            password=password,
            role='driver',
            company=company,
        )

    return Response(
        DriverSerializer(driver).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'PATCH', 'PUT', 'DELETE'])
@permission_classes([AllowAny])
def driver_detail(request, driver_id):
    """
    Retrieve, update, or delete a driver.

    GET:
        Public.

        Company staff are restricted to their own company.

    PATCH/PUT/DELETE:
        Company Managers may modify their own company's drivers.
        Superusers may modify any driver.
        Auditors, Operators, Drivers, and Passengers cannot modify drivers.
    """
    driver = get_object_or_404(
        Driver.objects.select_related('company'),
        id=driver_id,
    )

    if request.method == 'GET':
        if not _can_view_driver(request.user, driver):
            return Response(
                {
                    'error':
                    'You cannot access drivers from another company.'
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(
            DriverSerializer(driver).data,
            status=status.HTTP_200_OK,
        )

    if not _can_manage_driver(request.user, driver):
        return Response(
            {
                'error':
                'Only a Company Manager can modify drivers.'
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == 'DELETE':
        driver.delete()

        return Response(
            {'message': 'Driver removed successfully.'},
            status=status.HTTP_200_OK,
        )

    serializer = DriverSerializer(
        driver,
        data=request.data,
        partial=request.method == 'PATCH',
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Company is controlled by the server.
    # A manager cannot move a driver to another company.
    serializer.save(company=driver.company)

    return Response(
        DriverSerializer(driver).data,
        status=status.HTTP_200_OK,
    )


def _can_manage_driver_location(request, driver):
    """
    Determine whether the authenticated user can access or update
    this driver's operational location.

    Superuser:
        Any driver.

    Driver:
        Own driver record only.

    Company Manager:
        Drivers belonging to their company.

    Auditor/Operator:
        No access to the location-management endpoint.
    """
    user = request.user

    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    if user.role == 'driver':
        return user.phone_number == driver.phone_number

    return can_manage_company(user, driver.company)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([DriverLocationThrottle])
def driver_location(request, driver_id):
    """
    GET:
        Return driver location.

    POST:
        Driver can update their own location.
        Company Manager may update a company driver's location.
    """
    driver = get_object_or_404(
        Driver.objects.select_related('company'),
        id=driver_id,
    )

    if not _can_manage_driver_location(request, driver):
        return Response(
            {'error': 'Not authorized for this driver.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == 'GET':
        return Response(
            {
                'driver_id': driver.id,
                'name': driver.name,
                'latitude': driver.latitude,
                'longitude': driver.longitude,
                'location_updated_at': driver.location_updated_at,
            },
            status=status.HTTP_200_OK,
        )

    latitude = request.data.get('latitude')
    longitude = request.data.get('longitude')

    if latitude is None or longitude is None:
        return Response(
            {'error': 'latitude and longitude are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return Response(
            {'error': 'Invalid coordinates.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return Response(
            {'error': 'Coordinates are out of range.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    driver.latitude = latitude
    driver.longitude = longitude
    driver.location_updated_at = timezone.now()

    driver.save(
        update_fields=[
            'latitude',
            'longitude',
            'location_updated_at',
        ]
    )

    return Response(
        {
            'message': 'Driver location updated.',
            'driver_id': driver.id,
            'latitude': driver.latitude,
            'longitude': driver.longitude,
            'location_updated_at': driver.location_updated_at,
        },
        status=status.HTTP_200_OK,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_driver_profile(request):
    """
    Return the Driver record linked to the authenticated driver account.
    """
    if request.user.role != 'driver' and not request.user.is_superuser:
        return Response(
            {'error': 'Driver account required.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    driver = Driver.objects.select_related(
        'company'
    ).filter(
        phone_number=request.user.phone_number
    ).first()

    if not driver:
        return Response(
            {'error': 'No driver profile is linked to this account.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response(
        DriverSerializer(driver).data,
        status=status.HTTP_200_OK,
    )
