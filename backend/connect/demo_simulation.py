import math
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from companies.models import DemoTripSimulation, PickupStage, Route


SESSION_TTL = timedelta(minutes=20)
HISTORY_TTL = timedelta(days=7)
# The demo bus moves one path point per tick. Points are spaced evenly along
# the road so it keeps a steady speed and never cuts a corner.
STEP_METERS = 75
MIN_PATH_POINTS = 60
MAX_PATH_POINTS = 200


def _authorize(request):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Authentication required.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    if not request.user.is_superuser:
        return Response(
            {'error': 'Platform administrator access required.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    if not settings.DEMO_SIMULATION_ENABLED:
        return Response(
            {'error': 'Demo simulation is disabled on this server.'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return None


def _expire_old_sessions():
    now = timezone.now()
    DemoTripSimulation.objects.filter(
        status='running',
        expires_at__lte=now,
    ).update(status='expired', finished_at=now)
    DemoTripSimulation.objects.filter(
        expires_at__lt=now - HISTORY_TTL,
    ).delete()


def _coordinates_from_geometry(geometry):
    if isinstance(geometry, str):
        return []
    if not isinstance(geometry, dict):
        return []
    if geometry.get('type') == 'Feature':
        geometry = geometry.get('geometry') or {}
    if geometry.get('type') == 'FeatureCollection':
        features = geometry.get('features') or []
        first_feature = (
            features[0]
            if isinstance(features, list) and features
            else {}
        )
        geometry = (
            first_feature.get('geometry')
            if isinstance(first_feature, dict)
            else {}
        ) or {}
    if not isinstance(geometry, dict):
        return []

    coordinates = geometry.get('coordinates') or []
    if geometry.get('type') == 'LineString':
        lines = [coordinates]
    elif geometry.get('type') == 'MultiLineString':
        lines = coordinates
    else:
        return []

    points = []
    for line in lines:
        if not isinstance(line, (list, tuple)):
            continue
        for pair in line:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            try:
                longitude, latitude = float(pair[0]), float(pair[1])
            except (TypeError, ValueError, IndexError):
                continue
            if (
                math.isfinite(latitude)
                and math.isfinite(longitude)
                and -90 <= latitude <= 90
                and -180 <= longitude <= 180
            ):
                point = [latitude, longitude]
                if not points or point != points[-1]:
                    points.append(point)
    return points


def _valid_point(latitude, longitude):
    return (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    )


def _distance_squared(left, right):
    return (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2


def _route_path(route):
    stages = sorted(
        (stage for stage in route.pickup_stages.all() if stage.is_active),
        key=lambda stage: (stage.order, stage.id),
    )
    start = None
    if stages:
        candidate = [float(stages[0].latitude), float(stages[0].longitude)]
        if _valid_point(*candidate):
            start = candidate
    elif route.start_latitude is not None and route.start_longitude is not None:
        candidate = [float(route.start_latitude), float(route.start_longitude)]
        if _valid_point(*candidate):
            start = candidate

    points = _coordinates_from_geometry(route.geometry)
    if len(points) > 1 and start:
        if _distance_squared(points[-1], start) < _distance_squared(points[0], start):
            points.reverse()

    if not points:
        points = []
        for stage in stages:
            candidate = [float(stage.latitude), float(stage.longitude)]
            if _valid_point(*candidate):
                points.append(candidate)
    if start and (not points or _distance_squared(points[0], start) > 1e-10):
        points.insert(0, start)

    if route.end_latitude is not None and route.end_longitude is not None:
        end = [float(route.end_latitude), float(route.end_longitude)]
        if _valid_point(*end) and (
            not points or _distance_squared(points[-1], end) > 1e-10
        ):
            points.append(end)
    elif stages and len(points) <= 1:
        for stage in stages[1:]:
            candidate = [float(stage.latitude), float(stage.longitude)]
            if _valid_point(*candidate):
                points.append(candidate)

    unique = []
    for point in points:
        if not unique or _distance_squared(unique[-1], point) > 1e-14:
            unique.append(point)
    if len(unique) < 2:
        return []
    return _resample_evenly(unique)


def _meters(left, right):
    k = math.cos(math.radians((left[0] + right[0]) / 2))
    dy = (right[0] - left[0]) * 111320
    dx = (right[1] - left[1]) * 111320 * k
    return math.hypot(dx, dy)


def _resample_evenly(points):
    cumulative = [0.0]
    for left, right in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + _meters(left, right))
    total = cumulative[-1]
    if total <= 0:
        return []
    count = max(MIN_PATH_POINTS, min(MAX_PATH_POINTS, round(total / STEP_METERS) + 1))
    result = []
    segment = 0
    for index in range(count):
        target = total * index / (count - 1)
        while segment < len(points) - 2 and cumulative[segment + 1] < target:
            segment += 1
        span = cumulative[segment + 1] - cumulative[segment]
        t = 0.0 if span <= 0 else (target - cumulative[segment]) / span
        left, right = points[segment], points[segment + 1]
        result.append([
            round(left[0] + (right[0] - left[0]) * t, 6),
            round(left[1] + (right[1] - left[1]) * t, 6),
        ])
    return result


def _available_routes():
    routes = (
        Route.objects.select_related('company')
        .prefetch_related(
            Prefetch(
                'pickup_stages',
                queryset=PickupStage.objects.order_by('order', 'id'),
            )
        )
        .order_by('name', 'id')
    )
    return [
        {
            'id': route.id,
            'name': route.name,
            'company_name': route.company.name,
        }
        for route in routes
        if len(_route_path(route)) > 1
    ]


def _serialize(simulation):
    path = simulation.path
    index = min(simulation.position_index, len(path) - 1)
    return {
        'id': simulation.id,
        'route_id': simulation.route_id,
        'route_name': simulation.route_name,
        'company_name': simulation.company_name,
        'start_point': simulation.start_point,
        'end_point': simulation.end_point,
        'bus_number': simulation.bus_number,
        'path': path,
        'position_index': index,
        'position': path[index],
        'progress': round(index / max(len(path) - 1, 1) * 100),
        'status': simulation.status,
        'expires_at': simulation.expires_at.isoformat(),
    }


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def demo_simulation_collection(request):
    denied = _authorize(request)
    if denied:
        return denied
    _expire_old_sessions()

    active = DemoTripSimulation.objects.filter(status='running').first()
    if request.method == 'GET':
        latest = active or DemoTripSimulation.objects.first()
        return Response(
            {
                'simulation': _serialize(latest) if latest else None,
                'available_routes': _available_routes(),
            },
            status=status.HTTP_200_OK,
        )

    try:
        payload = request.data
        route_id_value = payload.get('route_id')
        if isinstance(route_id_value, bool):
            raise ValueError
        if isinstance(route_id_value, int):
            route_id = route_id_value
        elif isinstance(route_id_value, str) and route_id_value.strip().isdecimal():
            route_id = int(route_id_value.strip())
        else:
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        return Response(
            {'error': 'A valid route_id is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if active:
        if active.route_id == route_id:
            return Response(
                {'simulation': _serialize(active)},
                status=status.HTTP_200_OK,
            )
        return Response(
            {'error': 'Another demo simulation is already running. Stop it first.'},
            status=status.HTTP_409_CONFLICT,
        )

    route = (
        Route.objects.select_related('company')
        .filter(pk=route_id)
        .first()
    )
    if route is None:
        return Response(
            {'error': 'Route not found.'},
            status=status.HTTP_404_NOT_FOUND,
        )
    path = _route_path(route)
    if len(path) < 2:
        return Response(
            {'error': 'This route needs at least two valid map points to simulate.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        with transaction.atomic():
            simulation = DemoTripSimulation.objects.create(
                created_by=request.user,
                route_id=route.id,
                route_name=route.name,
                company_name=route.company.name,
                start_point=route.start_point,
                end_point=route.end_point,
                path=path,
                expires_at=timezone.now() + SESSION_TTL,
            )
    except IntegrityError:
        active = DemoTripSimulation.objects.filter(status='running').first()
        if active and active.route_id == route.id:
            return Response(
                {'simulation': _serialize(active)},
                status=status.HTTP_200_OK,
            )
        return Response(
            {'error': 'Another demo simulation is already running. Stop it first.'},
            status=status.HTTP_409_CONFLICT,
        )

    return Response(
        {'simulation': _serialize(simulation)},
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def advance_demo_simulation(request, simulation_id):
    denied = _authorize(request)
    if denied:
        return denied
    with transaction.atomic():
        simulation = (
            DemoTripSimulation.objects.select_for_update()
            .filter(pk=simulation_id)
            .first()
        )
        if simulation is None:
            return Response(
                {'error': 'Demo simulation not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if simulation.status != 'running':
            return Response(
                {'error': f'Demo simulation is {simulation.status}.'},
                status=status.HTTP_409_CONFLICT,
            )
        if simulation.expires_at <= timezone.now():
            simulation.status = 'expired'
            simulation.finished_at = timezone.now()
            simulation.save(update_fields=['status', 'finished_at', 'updated_at'])
            return Response(
                {'error': 'Demo simulation has expired.'},
                status=status.HTTP_410_GONE,
            )
        if simulation.position_index >= len(simulation.path) - 1:
            simulation.status = 'completed'
            simulation.finished_at = timezone.now()
        else:
            simulation.position_index += 1
            if simulation.position_index == len(simulation.path) - 1:
                simulation.status = 'completed'
                simulation.finished_at = timezone.now()
        simulation.save(
            update_fields=[
                'position_index',
                'status',
                'finished_at',
                'updated_at',
            ]
        )
    return Response(
        {'simulation': _serialize(simulation)},
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def stop_demo_simulation(request, simulation_id):
    denied = _authorize(request)
    if denied:
        return denied
    now = timezone.now()
    updated = DemoTripSimulation.objects.filter(
        pk=simulation_id,
        status='running',
        expires_at__gt=now,
    ).update(status='stopped', finished_at=now)
    if not updated:
        simulation = DemoTripSimulation.objects.filter(pk=simulation_id).first()
        if simulation is None:
            return Response(
                {'error': 'Demo simulation not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if simulation.status == 'running' and simulation.expires_at <= now:
            simulation.status = 'expired'
            simulation.finished_at = now
            simulation.save(update_fields=['status', 'finished_at', 'updated_at'])
            return Response(
                {'error': 'Demo simulation has expired.'},
                status=status.HTTP_410_GONE,
            )
        return Response(
            {'error': f'Demo simulation is already {simulation.status}.'},
            status=status.HTTP_409_CONFLICT,
        )
    simulation = DemoTripSimulation.objects.get(pk=simulation_id)
    return Response(
        {'simulation': _serialize(simulation)},
        status=status.HTTP_200_OK,
    )
