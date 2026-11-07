"""Platform-admin trip simulation: walk a trip's bus along its route line.

Each advance feeds one point through record_driver_fix, the same code a real
driver's GPS post runs, so live maps, auto-depart and SMS behave as in production.
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from companies.geo import orient_path, parse_geometry, resample_evenly
from companies.models import Trip, TripSimulation
from drivers.views import record_driver_fix

STEP_METERS = 75
SESSION_TTL = timedelta(minutes=30)
REAL_GPS_WINDOW = timedelta(seconds=60)
SIMULATABLE = ('scheduled', 'boarding', 'departed')


def _error(message, code):
    return Response({'error': message}, status=code)


def _superuser_only(request):
    if not request.user.is_superuser:
        return _error('Platform administrator access required.', status.HTTP_403_FORBIDDEN)
    return None


def _serialize(sim):
    last = len(sim.path) - 1
    index = min(sim.position_index, last)
    return {
        'id': sim.id,
        'trip_id': sim.trip_id,
        'status': sim.status,
        'position_index': index,
        'total_points': len(sim.path),
        'position': sim.path[index],
        'progress': round(index / max(last, 1) * 100),
        'trip_status': Trip.objects.values_list('status', flat=True).get(pk=sim.trip_id),
        'expires_at': sim.expires_at.isoformat(),
    }


def _expire_stale():
    TripSimulation.objects.filter(
        status='running', expires_at__lte=timezone.now()
    ).update(status='expired')


def _route_path(route):
    stages = list(
        route.pickup_stages.filter(is_active=True).order_by('order', 'id')
    )
    line = parse_geometry(route.geometry)
    if not line:
        # No drawn road line yet: drive stop to stop in stage order.
        line = [(float(s.latitude), float(s.longitude)) for s in stages]
        if len(line) < 2:
            return []
    elif stages:
        line = orient_path(line, (float(stages[0].latitude), float(stages[0].longitude)))
    return [[round(lat, 6), round(lng, 6)] for lat, lng in resample_evenly(line, STEP_METERS)]


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def start_trip_simulation(request, trip_id):
    denied = _superuser_only(request)
    if denied:
        return denied
    _expire_stale()
    trip = (
        Trip.objects.select_related('route', 'driver').filter(pk=trip_id).first()
    )
    if trip is None:
        return _error('Trip not found.', status.HTTP_404_NOT_FOUND)
    if trip.status not in SIMULATABLE:
        return _error(
            'Only scheduled, boarding or departed trips can be simulated.',
            status.HTTP_400_BAD_REQUEST,
        )
    if not trip.driver_id:
        return _error('Assign a driver first.', status.HTTP_400_BAD_REQUEST)
    path = _route_path(trip.route)
    if len(path) < 2:
        return _error(
            'This route needs a map line or at least two pickup stages. '
            'Add them in Route planner.',
            status.HTTP_400_BAD_REQUEST,
        )
    if TripSimulation.objects.filter(status='running').exists():
        return _error(
            'Another simulation is already running. Stop it first.',
            status.HTTP_409_CONFLICT,
        )
    fixed_at = trip.driver.location_updated_at
    if fixed_at and timezone.now() - fixed_at < REAL_GPS_WINDOW:
        # A fix left by our own earlier simulation is not a real driver.
        ours = TripSimulation.objects.filter(
            trip__driver_id=trip.driver_id, updated_at__gte=fixed_at
        ).exists()
        if not ours:
            return _error(
                'The driver sent GPS in the last minute. Wait or use the real driver.',
                status.HTTP_409_CONFLICT,
            )
    try:
        with transaction.atomic():
            sim = TripSimulation.objects.create(
                trip=trip,
                started_by=request.user,
                path=path,
                expires_at=timezone.now() + SESSION_TTL,
            )
    except IntegrityError:
        return _error(
            'Another simulation is already running. Stop it first.',
            status.HTTP_409_CONFLICT,
        )
    return Response({'simulation': _serialize(sim)}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def advance_trip_simulation(request, simulation_id):
    denied = _superuser_only(request)
    if denied:
        return denied
    with transaction.atomic():
        sim = (
            TripSimulation.objects.select_for_update(of=('self',))
            .filter(pk=simulation_id)
            .first()
        )
        if sim is None:
            return _error('Simulation not found.', status.HTTP_404_NOT_FOUND)
        if sim.status != 'running':
            return _error(f'Simulation is {sim.status}.', status.HTTP_409_CONFLICT)
        if sim.expires_at <= timezone.now():
            sim.status = 'expired'
            sim.save(update_fields=['status', 'updated_at'])
            return _error('Simulation has expired.', status.HTTP_410_GONE)
        last = len(sim.path) - 1
        sim.position_index = min(sim.position_index + 1, last)
        if sim.position_index >= last:
            sim.status = 'completed'
        sim.save(update_fields=['position_index', 'status', 'updated_at'])
        driver = sim.trip.driver
        lat, lng = sim.path[sim.position_index]
        record_driver_fix(driver, lat, lng)
    return Response({'simulation': _serialize(sim)}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def stop_trip_simulation(request, simulation_id):
    denied = _superuser_only(request)
    if denied:
        return denied
    updated = TripSimulation.objects.filter(
        pk=simulation_id, status='running'
    ).update(status='stopped')
    sim = TripSimulation.objects.filter(pk=simulation_id).first()
    if sim is None:
        return _error('Simulation not found.', status.HTTP_404_NOT_FOUND)
    if not updated:
        return _error(f'Simulation is already {sim.status}.', status.HTTP_409_CONFLICT)
    return Response({'simulation': _serialize(sim)}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def active_trip_simulation(request):
    denied = _superuser_only(request)
    if denied:
        return denied
    _expire_stale()
    sim = TripSimulation.objects.filter(status='running').first()
    return Response(
        {'simulation': _serialize(sim) if sim else None}, status=status.HTTP_200_OK
    )
