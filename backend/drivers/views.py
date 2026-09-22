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
    """List all drivers (public), or create a driver (authorized only)."""

    if request.method == 'GET':
        drivers = Driver.objects.select_related('company').all().order_by('id')
        serializer = DriverSerializer(drivers, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    # Creating a driver is a write that must be scoped to a company
    # the requester actually controls — this was previously wide
    # open to anyone, authenticated or not.
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required to add a driver.'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    company_id = request.data.get('company')
    try:
        company = Company.objects.get(id=company_id)
    except (Company.DoesNotExist, TypeError, ValueError):
        return Response(
            {'error': 'A valid company is required.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not can_manage_company(request.user, company):
        return Response(
            {'error': 'You are not authorized to add drivers for this company.'},
            status=status.HTTP_403_FORBIDDEN
        )

    serializer = DriverSerializer(data=request.data)

    if serializer.is_valid():
        driver = serializer.save()
        return Response(
            DriverSerializer(driver).data,
            status=status.HTTP_201_CREATED
        )

    return Response(
        serializer.errors,
        status=status.HTTP_400_BAD_REQUEST
    )


@api_view(['GET'])
@permission_classes([AllowAny])
def driver_detail(request, driver_id):
    """Retrieve driver details by ID."""

    try:
        driver = Driver.objects.select_related('company').get(
            id=driver_id
        )
    except Driver.DoesNotExist:
        return Response(
            {"error": "Driver not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = DriverSerializer(driver)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def driver_location(request, driver_id):
    """Retrieve the current location of a driver."""

    try:
        driver = Driver.objects.get(id=driver_id)
    except Driver.DoesNotExist:
        return Response(
            {"error": "Driver not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    return Response(
        {
            "driver_id": driver.id,
            "name": driver.name,
            "latitude": driver.latitude,
            "longitude": driver.longitude,
            "location_updated_at": driver.location_updated_at,
        },
        status=status.HTTP_200_OK
    )