from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from bookings.models import Booking, Payment, BoardingEvent
from users.permissions import can_manage_company
from wallets.models import Wallet
from .models import Company, Route, Trip
from .serializers import CompanySerializer, TripSerializer


@api_view(['GET'])
def get_companies(request, *args, **kwargs):
    """Fetch a list of all registered companies."""
    companies = Company.objects.all()
    serializer = CompanySerializer(companies, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
def get_routes(request, company_id=None, *args, **kwargs):
    """Fetch routes for a specific company or all routes."""
    # Accept company_id via URL parameter or query parameters
    comp_id = company_id or request.query_params.get('company_id')
    if comp_id:
        routes = Route.objects.filter(company_id=comp_id)
    else:
        routes = Route.objects.all()

    data = [
    {
        'id': r.id,
        'company': r.company.name if r.company else None,
        'name': r.name,
        'origin': r.start_point,
        'destination': r.end_point,
        'price': str(r.price),
    }
    for r in routes
]
    return Response(data, status=status.HTTP_200_OK)


@api_view(['GET'])
def get_trips(request, company_id=None, route_id=None, *args, **kwargs):
    """
    Fetch trips filtered by URL kwargs (company_id)
    or query parameters (?route_id=X).
    """
    queryset = Trip.objects.all()

    comp_id = company_id or request.query_params.get('company_id')
    if comp_id:
        queryset = queryset.filter(route__company_id=comp_id)

    param_route_id = route_id or request.query_params.get('route_id')
    if param_route_id:
        queryset = queryset.filter(route_id=param_route_id)

    serializer = TripSerializer(queryset, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
def get_trip_details(request, trip_id, *args, **kwargs):
    """Fetch single trip details using route__company span join."""
    try:
        trip = Trip.objects.select_related('route', 'driver', 'route__company').get(id=trip_id)
    except Trip.DoesNotExist:
        return Response({'error': 'Trip not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = TripSerializer(trip)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def company_analytics(request, company_id):
    """Fetch financial and operational metrics for a company."""
    company = get_object_or_404(
        Company.objects.select_related('user'),
        id=company_id,
    )

    # Safely resolve user's assigned company ID across direct attributes and relations
    user_company = getattr(request.user, 'company', None)
    user_company_id = getattr(request.user, 'company_id', getattr(user_company, 'id', None))

    if not request.user.is_staff and user_company_id != company.id:
        return Response(
            {'error': 'Unauthorized to view company analytics'},
            status=status.HTTP_403_FORBIDDEN
        )

    total_routes = Route.objects.filter(company=company).count()
    total_trips = Trip.objects.filter(route__company=company).count()

    # Settled revenue is the operator user's wallet available_balance
    # (credited on boarding). Company has no balance field.
    if company.user:
        try:
            company_balance = company.user.wallet.available_balance
        except Wallet.DoesNotExist:
            company_balance = Decimal('0.00')
    else:
        company_balance = Decimal('0.00')

    active_bookings = Booking.objects.filter(
        trip__route__company=company,
        status='confirmed',
    ).count()

    data = {
        'company_id': company.id,
        'company_name': company.name,
        'total_routes': total_routes,
        'total_trips': total_trips,
        'active_bookings': active_bookings,
        'total_revenue_settled': str(company_balance),
    }
    return Response(data, status=status.HTTP_200_OK)


@api_view(['POST', 'PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def update_trip_status(request, trip_id, *args, **kwargs):
    """Update a trip's status."""
    try:
        trip = Trip.objects.select_related('route__company').get(id=trip_id)
    except Trip.DoesNotExist:
        return Response({'error': 'Trip not found'}, status=status.HTTP_404_NOT_FOUND)

    if not can_manage_company(request.user, trip.route.company):
        return Response(
            {'error': 'You are not authorized to manage this company\'s trips.'},
            status=status.HTTP_403_FORBIDDEN
        )

    new_status = request.data.get('status')
    if not new_status:
        return Response(
            {'error': 'status parameter is required.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    valid_statuses = [
    'scheduled',
    'boarding',
    'departed',
    'completed',
    'cancelled',
    ]

    new_status = str(new_status).strip().lower()

    if new_status not in valid_statuses:
        return Response(
            {'error': f'Invalid status. Choose from: {valid_statuses}'},
            status=status.HTTP_400_BAD_REQUEST
        )

    with transaction.atomic():
        trip.status = new_status
        trip.save(update_fields=['status'])

    return Response({
        'message': 'Trip status updated successfully.',
        'trip_id': trip.id,
        'status': trip.status
    }, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_trip(request):
    """
    Create a trip for a company.

    Platform admins can create trips for any company.
    Company admins can only create trips for their own company.
    """

    company_id = request.data.get('company_id')
    route_id = request.data.get('route_id')
    driver_id = request.data.get('driver_id')
    departure_at = request.data.get('departure_at')
    capacity = request.data.get('capacity')

    if not all([company_id, route_id, driver_id, departure_at, capacity]):
        return Response(
            {
                'error': (
                    'company_id, route_id, driver_id, '
                    'departure_at and capacity are required.'
                )
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    company = get_object_or_404(Company, id=company_id)

    # Enforce company-level authorization.
    if not can_manage_company(request.user, company):
        return Response(
            {
                'error': (
                    "You are not authorized to create trips "
                    "for this company."
                )
            },
            status=status.HTTP_403_FORBIDDEN
        )

    # Import here to avoid unnecessary module-level coupling.
    from drivers.models import Driver

    route = get_object_or_404(
        Route,
        id=route_id,
        company=company
    )

    driver = get_object_or_404(
        Driver,
        id=driver_id,
        company=company
    )

    try:
        capacity = int(capacity)
    except (TypeError, ValueError):
        return Response(
            {'error': 'capacity must be a positive integer.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if capacity <= 0:
        return Response(
            {'error': 'capacity must be greater than zero.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if capacity > 100:
        return Response(
            {'error': 'capacity cannot exceed 100.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not departure_at:
        return Response(
            {'error': 'departure_at is required.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with transaction.atomic():
            trip = Trip.objects.create(
                route=route,
                driver=driver,
                departure_at=departure_at,
                capacity=capacity,
                status='scheduled',
            )
    except Exception:
        return Response(
            {'error': 'Unable to create trip.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    return Response(
        TripSerializer(trip).data,
        status=status.HTTP_201_CREATED
    )