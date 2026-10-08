from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from bookings.models import Booking, Payment, BoardingEvent
from users.permissions import (
    can_manage_company,
    can_access_company,
)
from wallets.models import Wallet
from .models import Company, Route, Trip, PickupStage
from .serializers import CompanySerializer, RouteSerializer, TripSerializer, PickupStageSerializer
from users.identity import is_driver_account_for


@api_view(['GET'])
@permission_classes([AllowAny])
def get_companies(request, *args, **kwargs):
    """Fetch a list of all registered companies."""
    companies = Company.objects.all()
    serializer = CompanySerializer(companies, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_company(request):
    """
    Create a company.

    Only the global platform administrator can create companies.
    Company managers cannot create companies.
    """
    if not request.user.is_superuser:
        return Response(
            {
                'error': (
                    'Only the platform administrator can create companies.'
                )
            },
            status=status.HTTP_403_FORBIDDEN
        )

    serializer = CompanySerializer(data=request.data)

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    company = serializer.save()

    return Response(
        CompanySerializer(company).data,
        status=status.HTTP_201_CREATED
    )


@api_view(['PATCH', 'PUT'])
@permission_classes([IsAuthenticated])
def update_company(request, company_id):
    """
    Update a company.

    Only the global platform administrator can update companies.
    """
    if not request.user.is_superuser:
        return Response(
            {
                'error': (
                    'Only the platform administrator can update companies.'
                )
            },
            status=status.HTTP_403_FORBIDDEN
        )

    company = get_object_or_404(
        Company,
        id=company_id
    )

    serializer = CompanySerializer(
        company,
        data=request.data,
        partial=request.method == 'PATCH'
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    company = serializer.save()

    return Response(
        CompanySerializer(company).data,
        status=status.HTTP_200_OK
    )


@api_view(['GET'])
@permission_classes([AllowAny])
def get_routes(request, company_id=None, *args, **kwargs):
    """
    Fetch routes.

    Passengers and unauthenticated users may browse routes
    across companies.

    Company staff may only access routes belonging to
    their own company.

    Superusers may access routes for any company.
    """
    user = request.user

    company_staff_roles = {
        'company_manager',
        'company_auditor',
        'company_operator',
    }

    is_company_staff = (
        user.is_authenticated
        and not user.is_superuser
        and user.role in company_staff_roles
    )

    comp_id = (
        company_id
        or request.query_params.get('company_id')
        or request.query_params.get('company')
    )

    if is_company_staff:
        if user.company_id is None:
            return Response(
                {'error': 'Company assignment required.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if comp_id and str(comp_id) != str(user.company_id):
            return Response(
                {
                    'error': (
                        'You cannot access routes '
                        'from another company.'
                    )
                },
                status=status.HTTP_403_FORBIDDEN
            )

        routes = Route.objects.filter(
            company_id=user.company_id
        )

    elif comp_id:
        routes = Route.objects.filter(
            company_id=comp_id
        )

    else:
        routes = Route.objects.all()

    routes = routes.select_related('company').prefetch_related(
        'pickup_stages'
    )

    data = []

    for route in routes:
        pickup_stages = [
            {
                'id': stage.id,
                'route': route.id,
                'name': stage.name,
                'latitude': float(stage.latitude),
                'longitude': float(stage.longitude),
                'order': stage.order,
                'is_active': stage.is_active,
            }
            for stage in route.pickup_stages.all()
            if stage.is_active
        ]

        data.append({
            'id': route.id,
            'company': route.company_id,
            'company_name': route.company.name if route.company else None,
            'name': route.name,
            'start_point': route.start_point,
            'end_point': route.end_point,
            'origin': route.start_point,
            'destination': route.end_point,
            'price': str(route.price),
            'start_latitude': (
                float(route.start_latitude)
                if route.start_latitude is not None else None
            ),
            'start_longitude': (
                float(route.start_longitude)
                if route.start_longitude is not None else None
            ),
            'end_latitude': (
                float(route.end_latitude)
                if route.end_latitude is not None else None
            ),
            'end_longitude': (
                float(route.end_longitude)
                if route.end_longitude is not None else None
            ),
            'geometry': route.geometry,
            'via_points': route.via_points or [],
            'pickup_stages': pickup_stages,
        })


    return Response(
        data,
        status=status.HTTP_200_OK
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_route(request):
    """
    Create a route for a company.

    Company Managers can create routes only for their own company.
    Django superusers can create routes for any company.

    The company relationship is determined by the server and cannot
    be changed through RouteSerializer.
    """
    company_id = request.data.get('company_id')

    if not company_id:
        return Response(
            {'error': 'company_id is required.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    company = get_object_or_404(
        Company,
        id=company_id
    )

    if not can_manage_company(request.user, company):
        return Response(
            {
                'error': (
                    'Only a Company Manager can create routes '
                    'for this company.'
                )
            },
            status=status.HTTP_403_FORBIDDEN
        )

    serializer = RouteSerializer(
        data=request.data
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    route = serializer.save(
        company=company
    )

    return Response(
        RouteSerializer(route).data,
        status=status.HTTP_201_CREATED
    )


@api_view(['PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def manage_route(request, route_id):
    """
    Edit or delete a route.

    Company Managers can manage routes belonging to their company.
    Django superusers can manage routes for any company.

    The route's company cannot be changed.
    """
    route = get_object_or_404(
        Route.objects.select_related('company'),
        id=route_id
    )

    if not can_manage_company(
        request.user,
        route.company
    ):
        return Response(
            {
                'error': (
                    'Only a Company Manager can manage '
                    'this route.'
                )
            },
            status=status.HTTP_403_FORBIDDEN
        )

    if request.method == 'DELETE':
        try:
            with transaction.atomic():
                locked_route = (
                    Route.objects
                    .select_for_update()
                    .get(pk=route.pk)
                )

                has_trip_history = locked_route.trips.exists()
                has_booking_history = locked_route.bookings.exists()

                if has_trip_history or has_booking_history:
                    return Response(
                        {
                            'error': (
                                'This route has operational history and '
                                'cannot be deleted. Keep it for historical '
                                'reference and use a new route for future '
                                'operations.'
                            )
                        },
                        status=status.HTTP_409_CONFLICT
                    )

                locked_route.delete()

        except Route.DoesNotExist:
            return Response(
                {'error': 'Route not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(
            {
                'message': 'Route deleted successfully.'
            },
            status=status.HTTP_200_OK
        )

    serializer = RouteSerializer(
        route,
        data=request.data,
        partial=request.method == 'PATCH'
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    updated_route = serializer.save(
        company=route.company
    )

    return Response(
        RouteSerializer(updated_route).data,
        status=status.HTTP_200_OK
    )


@api_view(['GET'])
@permission_classes([AllowAny])
def get_trips(request, company_id=None, route_id=None, *args, **kwargs):
    """
    Fetch trips.

    Passengers and unauthenticated users may browse trips across companies.
    Company staff may only access trips belonging to their own company.
    Superusers may access every company.
    """
    queryset = Trip.objects.select_related(
        'route',
        'driver',
        'route__company',
    )

    user = request.user
    company_staff_roles = {
        'company_manager',
        'company_auditor',
        'company_operator',
    }

    is_company_staff = (
        user.is_authenticated
        and not user.is_superuser
        and user.role in company_staff_roles
    )

    comp_id = (
        company_id
        or request.query_params.get('company_id')
        or request.query_params.get('company')
    )

    if is_company_staff:
        if user.company_id is None:
            return Response(
                {'error': 'Company assignment required.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if comp_id and str(comp_id) != str(user.company_id):
            return Response(
                {'error': 'You cannot access trips from another company.'},
                status=status.HTTP_403_FORBIDDEN
            )

        queryset = queryset.filter(
            route__company_id=user.company_id
        )

    elif comp_id:
        queryset = queryset.filter(
            route__company_id=comp_id
        )

    param_route_id = (
        route_id
        or request.query_params.get('route_id')
    )

    if param_route_id:
        queryset = queryset.filter(
            route_id=param_route_id
        )

    # Passengers should only see trips that are still bookable.
    # Company staff and superusers retain access to historical trips.
    if not is_company_staff and not user.is_superuser:
        from django.utils import timezone
        queryset = queryset.filter(
            status='scheduled',
            departure_at__gt=timezone.now(),
        )

    serializer = TripSerializer(queryset, many=True)
    return Response(
        serializer.data,
        status=status.HTTP_200_OK
    )

@api_view(['GET'])
@permission_classes([AllowAny])
def get_trip_details(request, trip_id, *args, **kwargs):
    """
    Fetch a single trip.

    Company staff may only access trips belonging to their company.
    Passengers and unauthenticated users may view trip details.
    Superusers may view any trip.
    """
    try:
        trip = Trip.objects.select_related(
            'route',
            'driver',
            'route__company',
        ).get(id=trip_id)
    except Trip.DoesNotExist:
        return Response(
            {'error': 'Trip not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    user = request.user
    company_staff_roles = {
        'company_manager',
        'company_auditor',
        'company_operator',
    }

    if (
        user.is_authenticated
        and not user.is_superuser
        and user.role in company_staff_roles
    ):
        if user.company_id is None:
            return Response(
                {'error': 'Company assignment required.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if trip.route.company_id != user.company_id:
            return Response(
                {'error': 'You cannot access trips from another company.'},
                status=status.HTTP_403_FORBIDDEN
            )

    serializer = TripSerializer(trip)
    return Response(
        serializer.data,
        status=status.HTTP_200_OK
    )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def company_analytics(request, company_id):
    """Fetch financial and operational metrics for a company."""
    company = get_object_or_404(
        Company.objects.select_related('user'),
        id=company_id,
    )

    # Company access is enforced by role and company assignment.
    if not can_access_company(request.user, company.id):
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
    """Update a trip's status using the operational state machine."""
    try:
        trip = (
            Trip.objects
            .select_related('route__company')
            .get(id=trip_id)
        )
    except Trip.DoesNotExist:
        return Response(
            {'error': 'Trip not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    user = request.user
    company = trip.route.company

    allowed = (
        user.is_superuser
        or (
            user.role in {'company_manager', 'company_operator'}
            and user.company_id == company.id
        )
    )

    if not allowed:
        return Response(
            {
                'error':
                'You are not authorized to manage this company\'s trips.'
            },
            status=status.HTTP_403_FORBIDDEN
        )

    new_status = request.data.get('status')
    if not new_status:
        return Response(
            {'error': 'status parameter is required.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    new_status = str(new_status).strip().lower()

    valid_statuses = {
        'scheduled',
        'boarding',
        'departed',
        'completed',
        'cancelled',
    }

    if new_status not in valid_statuses:
        return Response(
            {
                'error': (
                    'Invalid status. Choose from: '
                    f'{sorted(valid_statuses)}'
                )
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    current_status = trip.status

    allowed_transitions = {
        'scheduled': {'scheduled', 'boarding', 'cancelled'},
        'boarding': {'boarding', 'departed', 'cancelled'},
        'departed': {'departed', 'completed'},
        'completed': {'completed'},
        'cancelled': {'cancelled'},
    }

    if new_status not in allowed_transitions[current_status]:
        return Response(
            {
                'error': (
                    f'Invalid trip transition: '
                    f'{current_status} -> {new_status}.'
                ),
                'current_status': current_status,
                'requested_status': new_status,
            },
            status=status.HTTP_409_CONFLICT
        )

    with transaction.atomic():
        trip = (
            Trip.objects
            .select_for_update()
            .select_related('route__company')
            .get(pk=trip.pk)
        )

        # Re-check against the locked current state so two concurrent
        # status updates cannot bypass the transition rules.
        current_status = trip.status

        if new_status not in allowed_transitions[current_status]:
            return Response(
                {
                    'error': (
                        f'Invalid trip transition: '
                        f'{current_status} -> {new_status}.'
                    ),
                    'current_status': current_status,
                    'requested_status': new_status,
                },
                status=status.HTTP_409_CONFLICT
            )

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

    departure = parse_datetime(str(departure_at))
    if departure is None:
        return Response(
            {'error': 'departure_at must be a valid ISO datetime.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    if timezone.is_naive(departure):
        departure = timezone.make_aware(departure, timezone.get_current_timezone())
    if departure <= timezone.now():
        return Response(
            {'error': 'departure_at must be in the future.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    with transaction.atomic():
        driver = get_object_or_404(
            Driver.objects.select_for_update(),
            id=driver_id,
            company=company,
        )

        if not driver.is_available:
            return Response(
                {
                    'error': (
                        'This driver is currently unavailable and '
                        'cannot be assigned to a new trip.'
                    )
                },
                status=status.HTTP_409_CONFLICT
            )

        conflicting_trip = (
            Trip.objects
            .filter(
                driver=driver,
                departure_at=departure,
                status__in={
                    'scheduled',
                    'boarding',
                    'departed',
                },
            )
            .exists()
        )

        if conflicting_trip:
            return Response(
                {
                    'error': (
                        'This driver is already assigned to another '
                        'active trip at the requested departure time.'
                    )
                },
                status=status.HTTP_409_CONFLICT
            )

        trip = Trip.objects.create(
            route=route,
            driver=driver,
            departure_at=departure,
            capacity=capacity,
            status='scheduled',
        )

    return Response(
        TripSerializer(trip).data,
        status=status.HTTP_201_CREATED
    )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_route_pickup_stages(request, route_id):
    """
    Return pickup stages for a route.

    Company staff can view stages for their own company.
    Platform admins can view stages for any company.
    """
    route = get_object_or_404(
        Route.objects.select_related('company'),
        id=route_id,
    )

    if not can_access_company(request.user, route.company_id):
        return Response(
            {'error': 'You do not have access to this company route.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    stages = PickupStage.objects.filter(
        route=route,
    ).order_by('order', 'id')

    return Response(
        PickupStageSerializer(stages, many=True).data,
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_pickup_stage(request, route_id):
    """
    Create a manually verified pickup stage for a route.

    Only company managers or the platform administrator can create stages.
    """
    route = get_object_or_404(
        Route.objects.select_related('company'),
        id=route_id,
    )

    if not can_manage_company(request.user, route.company):
        return Response(
            {'error': 'Only a Company Manager can manage pickup stages.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    data = request.data.copy()
    data['route'] = route.id
    data['source'] = 'manual'

    serializer = PickupStageSerializer(data=data)

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

    from django.db import transaction
    from django.db.models import F
    from .geo import MAX_STAGE_OFFSET_M, locate_on_line

    new_order = None
    here = locate_on_line(
        route.geometry,
        float(serializer.validated_data['latitude']),
        float(serializer.validated_data['longitude']),
    )
    if here is not None:
        if here[0] > MAX_STAGE_OFFSET_M:
            return Response(
                {'error': (
                    f'That point is about {round(here[0])} m from the route line. '
                    f'Place the stage on the road the bus uses (within {MAX_STAGE_OFFSET_M} m).'
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )
        existing = list(route.pickup_stages.order_by('order', 'id'))
        new_order = max([s.order for s in existing], default=0) + 1
        for s in existing:
            loc = locate_on_line(route.geometry, float(s.latitude), float(s.longitude))
            if loc is not None and loc[1] > here[1]:
                new_order = s.order
                break

    with transaction.atomic():
        if new_order is not None:
            route.pickup_stages.filter(order__gte=new_order).update(order=F('order') + 1)
        extra = {'order': new_order} if new_order is not None else {}
        stage = serializer.save(route=route, source='manual', **extra)

    return Response(
        PickupStageSerializer(stage).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['PATCH', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def manage_pickup_stage(request, stage_id):
    """
    Edit, deactivate, or delete a pickup stage.

    The stage can only be managed by the company manager of its route's
    company or the platform administrator.
    """
    stage = get_object_or_404(
        PickupStage.objects.select_related('route__company'),
        id=stage_id,
    )

    if not can_manage_company(
        request.user,
        stage.route.company,
    ):
        return Response(
            {'error': 'Only a Company Manager can manage this pickup stage.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == 'DELETE':
        stage.delete()

        return Response(
            {'message': 'Pickup stage deleted successfully.'},
            status=status.HTTP_200_OK,
        )

    data = request.data.copy()

    # Route ownership and discovery provenance are controlled by the server.
    data.pop('route', None)
    data.pop('source', None)
    data.pop('source_ref', None)

    serializer = PickupStageSerializer(
        stage,
        data=data,
        partial=request.method == 'PATCH',
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

    stage = serializer.save()

    return Response(
        PickupStageSerializer(stage).data,
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_pickup_stage(request, stage_id):
    """
    Approve an automatically discovered pickup stage.

    Approval changes its source to manual, meaning the company has
    explicitly verified the stage.
    """
    stage = get_object_or_404(
        PickupStage.objects.select_related('route__company'),
        id=stage_id,
    )

    if not can_manage_company(
        request.user,
        stage.route.company,
    ):
        return Response(
            {'error': 'Only a Company Manager can approve pickup stages.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    stage.source = 'manual'
    stage.is_active = True
    stage.save(
        update_fields=['source', 'is_active'],
    )

    return Response(
        {
            'message': 'Pickup stage approved successfully.',
            'stage': PickupStageSerializer(stage).data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def deactivate_pickup_stage(request, stage_id):
    """
    Deactivate a pickup stage without deleting its record.
    """
    stage = get_object_or_404(
        PickupStage.objects.select_related('route__company'),
        id=stage_id,
    )

    if not can_manage_company(
        request.user,
        stage.route.company,
    ):
        return Response(
            {'error': 'Only a Company Manager can manage pickup stages.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    stage.is_active = False
    stage.save(update_fields=['is_active'])

    return Response(
        {
            'message': 'Pickup stage deactivated successfully.',
            'stage': PickupStageSerializer(stage).data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(['GET'])
@permission_classes([AllowAny])
def route_map_data(request, route_id):
    from django.db.models import Count, Sum
    from .models import Route, Trip
    from bookings.models import Booking

    try:
        route = Route.objects.get(id=route_id)
    except Route.DoesNotExist:
        return Response({"error": "Route not found."}, status=status.HTTP_404_NOT_FOUND)

    trip_id = request.query_params.get("trip_id")
    trip = None

    if trip_id:
        try:
            trip = Trip.objects.select_related("route").get(id=trip_id)
        except Trip.DoesNotExist:
            return Response({"error": "Trip not found."}, status=status.HTTP_404_NOT_FOUND)

        if trip.route_id != route.id:
            return Response(
                {"error": "Trip does not belong to this route."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    can_see_private_trip_data = (
        trip is not None
        and _can_see_route_passengers(request.user, route, trip)
    )

    stages = route.pickup_stages.filter(is_active=True).order_by("order", "id")
    stage_data = []

    for stage in stages:
        booking_qs = Booking.objects.none()

        if trip:
            booking_qs = Booking.objects.filter(
                trip=trip,
                pickup_stage_id=stage.id,
            ).exclude(status="cancelled")

            if not booking_qs.exists():
                booking_qs = Booking.objects.filter(
                    trip=trip,
                    pickup_stage__isnull=True,
                    pickup_location__iexact=stage.name,
                ).exclude(status="cancelled")

        counts = booking_qs.aggregate(
            booking_count=Count("id"),
            passenger_count=Sum("seats"),
        )

        passengers = []

        if can_see_private_trip_data:
            for booking in booking_qs.select_related("user").order_by(
                "created_at",
                "id",
            ):
                passengers.append({
                    "booking_id": booking.id,
                    "booking_number": booking.booking_number,
                    "passenger": booking.user.username,
                    "passenger_phone": booking.user.phone_number,
                    "seats": booking.seats,
                    "status": booking.status,
                    "pickup_stage_id": (
                        booking.pickup_stage_id
                    ),
                    "pickup_location": booking.pickup_location,
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
                })

        stage_data.append({
            "id": stage.id,
            "name": stage.name,
            "latitude": float(stage.latitude),
            "longitude": float(stage.longitude),
            "order": stage.order,
            "source": stage.source,
            "booking_count": int(counts["booking_count"] or 0),
            "passenger_count": int(counts["passenger_count"] or 0),
            "passengers": passengers,
        })

    return Response({
        "route_id": route.id,
        "route_name": route.name,
        "start_point": route.start_point,
        "end_point": route.end_point,
        "trip_id": trip.id if trip else None,
        "departure_at": trip.departure_at if trip else None,
        "geometry": route.geometry or {"type": "LineString", "coordinates": []},
        "stages": stage_data,
    })


def _can_access_route_trip_map(user, route, trip):
    """
    Authorize access to a trip-specific operational map.

    Public users may browse a route map without a trip selected.
    Trip-specific operational data is restricted to:
    - platform admins
    - company staff from the route's company
    - the assigned driver
    - a passenger who actually booked the trip
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    if getattr(user, 'role', None) in {
        'company_manager',
        'company_auditor',
        'company_operator',
    }:
        return (
            user.company_id is not None
            and user.company_id == route.company_id
        )

    if getattr(user, 'role', None) == 'driver':
        driver = trip.driver
        return (
            driver is not None
            and is_driver_account_for(user, driver)
        )

    return Booking.objects.filter(
        trip=trip,
        user=user,
    ).exists()


def _can_see_route_passengers(user, route, trip):
    """Passenger names, phones and positions are private."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    role = getattr(user, 'role', None)
    if role in {'company_manager', 'company_auditor', 'company_operator'}:
        return user.company_id is not None and user.company_id == route.company_id
    if role == 'driver':
        driver = trip.driver
        return driver is not None and is_driver_account_for(user, driver)
    return False


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def route_plan(request, route_id):
    """Preview or save a route's start, end and road-following line.

    The line is always generated here from the start, the end, the active
    stages and optional road points, so a client can never store its own line.
    """
    from datetime import timedelta
    from decimal import Decimal

    from django.utils import timezone

    from .geo import MAX_STAGE_OFFSET_M, locate_on_line
    from .routing import RoutingError, road_line

    route = get_object_or_404(Route.objects.select_related('company'), id=route_id)
    if not can_manage_company(request.user, route.company):
        return Response(
            {'error': 'Only a Company Manager can plan routes.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    data = request.data

    def end_point(key, name, lat, lng):
        raw = data.get(key)
        if raw is None and lat is not None and lng is not None:
            raw = {'name': name, 'latitude': lat, 'longitude': lng}
        return raw

    def read(raw, label):
        if not isinstance(raw, dict):
            raise ValueError(f'Choose the {label} point on the map.')
        try:
            lat, lng = float(raw.get('latitude')), float(raw.get('longitude'))
        except (TypeError, ValueError):
            raise ValueError(f'Choose the {label} point on the map.')
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError(f'The {label} point is not a valid place.')
        return lat, lng, str(raw.get('name') or '').strip()[:100]

    try:
        s_lat, s_lng, s_name = read(
            end_point('start', route.start_point, route.start_latitude, route.start_longitude), 'start')
        e_lat, e_lng, e_name = read(
            end_point('end', route.end_point, route.end_latitude, route.end_longitude), 'end')
        raw_via = (data.get('via') if 'via' in data else route.via_points) or []
        if not isinstance(raw_via, list) or len(raw_via) > 10:
            raise ValueError('Use at most 10 road points.')
        vias = []
        for i, raw in enumerate(raw_via, start=1):
            v_lat, v_lng, _ = read(raw, f'road point {i}')
            vias.append((v_lat, v_lng))
    except ValueError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    apply = data.get('apply') is True

    if apply:
        if not s_name or not e_name:
            return Response(
                {'error': 'Give the start and the end a name before saving.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        now = timezone.now()
        running = Trip.objects.filter(
            route=route,
            status__in=['boarding', 'departed'],
            departure_at__gte=now - timedelta(hours=12),
            departure_at__lte=now + timedelta(hours=3),
        ).exists()
        if running:
            return Response(
                {'error': 'A bus is running on this route right now. Change the road line when no trip is running.'},
                status=status.HTTP_409_CONFLICT,
            )

    stages = list(route.pickup_stages.filter(is_active=True).order_by('order', 'id'))

    def fallback_key(lat, lng):
        return (
            (lat - s_lat) * (e_lat - s_lat)
            + (lng - s_lng) * (e_lng - s_lng)
        )

    controls = []

    # Stages do NOT steer the line. A bus follows its real road; stages sit on
    # it, and any stage off the line is reported in off_route below. Only the
    # manager's road points (via) steer the line.

    for index, point in enumerate(vias):
        controls.append({
            'kind': 'via',
            'lat': float(point[0]),
            'lng': float(point[1]),
            'order': 0,
            'index': index,
        })

    # When a saved route already exists, use that route as the
    # authority for the ordering of new control points.
    #
    # This is much safer than projecting everything onto the
    # straight start -> end line, because real Nairobi routes
    # bend, loop, and sometimes temporarily move away from the
    # final destination.
    existing_positions = []

    if (
        isinstance(route.geometry, dict)
        and route.geometry.get('type') == 'LineString'
        and len(route.geometry.get('coordinates') or []) >= 2
    ):
        for control in controls:
            loc = locate_on_line(
                route.geometry,
                control['lat'],
                control['lng'],
            )

            if loc is None:
                existing_positions = []
                break

            existing_positions.append(loc[1])

    if existing_positions and len(existing_positions) == len(controls):
        for control, along_m in zip(controls, existing_positions):
            control['along_m'] = along_m

        controls.sort(
            key=lambda item: (
                item['along_m'],
                item['kind'] != 'stage',
                item['order'],
                item['index'],
            )
        )
    else:
        # No established route exists yet. Fall back to the
        # previous deterministic ordering.
        controls.sort(
            key=lambda item: (
                fallback_key(item['lat'], item['lng']),
                item['kind'] != 'stage',
                item['order'],
                item['index'],
            )
        )

    waypoints = [(s_lat, s_lng)]

    for control in controls:
        waypoints.append(
            (control['lat'], control['lng'])
        )

    waypoints.append((e_lat, e_lng))
    if len(waypoints) > 30:
        return Response(
            {'error': 'Too many stages and road points for one line.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        geometry, distance_m = road_line(waypoints)
    except RoutingError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    off_route = []
    for s in stages:
        loc = locate_on_line(geometry, float(s.latitude), float(s.longitude))
        if loc is not None and loc[0] > MAX_STAGE_OFFSET_M:
            off_route.append({'id': s.id, 'name': s.name, 'offset_m': round(loc[0])})

    if apply:
        route.start_point, route.end_point = s_name, e_name
        route.start_latitude, route.start_longitude = Decimal(f'{s_lat:.6f}'), Decimal(f'{s_lng:.6f}')
        route.end_latitude, route.end_longitude = Decimal(f'{e_lat:.6f}'), Decimal(f'{e_lng:.6f}')
        route.geometry = geometry
        route.via_points = [{'latitude': v[0], 'longitude': v[1]} for v in vias]
        route.save(update_fields=[
            'start_point', 'end_point', 'start_latitude', 'start_longitude',
            'end_latitude', 'end_longitude', 'geometry', 'via_points',
        ])

    return Response({
        'applied': apply,
        'geometry': geometry,
        'distance_km': round(distance_m / 1000, 1),
        'off_route_stages': off_route,
        'via': [{'latitude': v[0], 'longitude': v[1]} for v in vias],
    })



@api_view(['GET'])
@permission_classes([IsAuthenticated])
def route_health(request):
    """Advisory shape check of every route the caller manages."""
    from .geo import MAX_STAGE_OFFSET_M, line_health

    routes = Route.objects.select_related('company').prefetch_related('pickup_stages')
    if not request.user.is_superuser:
        routes = routes.filter(company_id=request.user.company_id)

    results = []
    for route in routes.order_by('id'):
        if not can_manage_company(request.user, route.company):
            continue
        stages = [
            (s.id, s.name, float(s.latitude), float(s.longitude))
            for s in route.pickup_stages.all() if s.is_active
        ]
        h = line_health(route.geometry, stages)
        reasons = []
        if not h['has_line']:
            reasons.append('No road line yet')
        if h['spurs']:
            reasons.append(f"{h['spurs']} place(s) where the line turns back on itself")
        if h['detour_ratio'] and h['detour_ratio'] > 2.5:
            reasons.append('The line is much longer than the straight distance')
        if h['stages_off']:
            reasons.append(f"{len(h['stages_off'])} stage(s) more than {MAX_STAGE_OFFSET_M} m from the line")
        results.append({
            'id': route.id,
            'name': route.name,
            'status': 'check' if reasons else 'ok',
            'reasons': reasons,
            'length_km': h['length_km'],
            'detour_ratio': h['detour_ratio'],
            'spur_points': h['spur_points'],
            'stages_off': h['stages_off'],
            'road_points': len(route.via_points or []),
        })
    return Response(results)
