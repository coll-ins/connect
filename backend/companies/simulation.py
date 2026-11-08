"""Platform-admin trip simulation: walk a trip's bus along its route line.

Each advance feeds one point through record_driver_fix, the same code a real
driver's GPS post runs, so live maps, auto-depart and SMS behave as in production.
"""
import math
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
DIVERT_POINTS = 40
DIVERT_OFFSET_M = 300
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
            if trip.status == 'scheduled':
                # Passenger maps only track boarding or departed trips, and
                # auto-depart only runs from boarding.
                trip.status = 'boarding'
                trip.save(update_fields=['status'])
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
        trip = sim.trip
        driver = trip.driver
        if trip.status not in SIMULATABLE or driver is None:
            sim.status = 'stopped'
            sim.save(update_fields=['status', 'updated_at'])
            return _error(
                f'The trip is {trip.status}; the simulation stopped.',
                status.HTTP_409_CONFLICT,
            )
        if driver.location_updated_at and driver.location_updated_at > sim.updated_at:
            # The real driver sent GPS since our last tick: never overwrite it.
            sim.status = 'stopped'
            sim.save(update_fields=['status', 'updated_at'])
            return _error(
                'The real driver is sending GPS; the simulation stopped.',
                status.HTTP_409_CONFLICT,
            )
        last = len(sim.path) - 1
        sim.position_index = min(sim.position_index + 1, last)
        if sim.position_index >= last:
            sim.status = 'completed'
        lat, lng = sim.path[sim.position_index]
        record_driver_fix(driver, lat, lng, simulated=True)
        # Saved after the fix so our own GPS write never counts as "newer".
        sim.save(update_fields=['position_index', 'status', 'updated_at'])
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


def diverted_path(path, index):
    """The path with the next stretch bowed out sideways, as if on another road.

    Starts and ends on the route so the bus leaves it and comes back.
    """
    end = min(index + DIVERT_POINTS, len(path) - 1)
    if end - index < 4:
        return None
    (from_lat, from_lng), (to_lat, to_lng) = path[index], path[end]
    metres_per_lng = 111320 * math.cos(math.radians(from_lat))
    east = (to_lng - from_lng) * metres_per_lng
    north = (to_lat - from_lat) * 110574
    length = math.hypot(east, north)
    if length < 1:
        return None
    side_east, side_north = -north / length, east / length

    bent = [list(point) for point in path]
    for i in range(index + 1, end):
        bow = math.sin(math.pi * (i - index) / (end - index)) * DIVERT_OFFSET_M
        bent[i] = [
            round(path[i][0] + side_north * bow / 110574, 6),
            round(path[i][1] + side_east * bow / metres_per_lng, 6),
        ]
    return bent


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def divert_trip_simulation(request, simulation_id):
    """Send the simulated bus off its route, to test rerouting."""
    denied = _superuser_only(request)
    if denied:
        return denied
    with transaction.atomic():
        sim = (
            TripSimulation.objects.select_for_update()
            .filter(pk=simulation_id)
            .first()
        )
        if sim is None:
            return _error('Simulation not found.', status.HTTP_404_NOT_FOUND)
        if sim.status != 'running':
            return _error(f'Simulation is {sim.status}.', status.HTTP_409_CONFLICT)
        bent = diverted_path(sim.path, sim.position_index)
        if bent is None:
            return _error(
                'The bus is too close to the end of the route to divert.',
                status.HTTP_409_CONFLICT,
            )
        sim.path = bent
        sim.save(update_fields=['path', 'updated_at'])
    return Response({'simulation': _serialize(sim)}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def finish_simulated_trip(request, trip_id):
    """End a trip from the admin screen, by the same rule as the driver's End trip."""
    denied = _superuser_only(request)
    if denied:
        return denied
    from bookings.services import run_refund_claims, settle_unboarded_no_shows

    claims = []
    with transaction.atomic():
        trip = Trip.objects.select_for_update().filter(pk=trip_id).first()
        if trip is None:
            return _error('Trip not found.', status.HTTP_404_NOT_FOUND)
        if trip.status not in ('boarding', 'departed'):
            return _error(
                'Only a boarding or departed trip can be ended.',
                status.HTTP_409_CONFLICT,
            )
        TripSimulation.objects.filter(trip=trip, status='running').update(status='stopped')
        settled, protected = settle_unboarded_no_shows(trip, claims=claims)
        trip.status = 'completed'
        trip.save(update_fields=['status'])

    # Paystack is called only after the trip lock has been released.
    run_refund_claims(claims)
    return Response(
        {
            'trip_id': trip.id,
            'status': trip.status,
            'no_shows_settled': settled,
            'incident_protected': protected,
        },
        status=status.HTTP_200_OK,
    )


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
