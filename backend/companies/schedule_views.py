from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from drivers.models import Driver

from .models import Company, Route, Trip, TripSchedule
from .trip_generation import regenerate_for_schedule
from .views import can_manage_company


def _bad(msg, code=status.HTTP_400_BAD_REQUEST):
    return Response({'error': msg}, status=code)


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _days(v):
    if not isinstance(v, (list, tuple)) or not v:
        return None
    out = set()
    for x in v:
        n = _int(x)
        if n is None or isinstance(x, bool) or not 0 <= n <= 6:
            return None
        out.add(n)
    return ','.join(str(n) for n in sorted(out))


def _data(s):
    return {
        'id': s.id,
        'company_id': s.route.company_id,
        'route_id': s.route_id,
        'route_name': s.route.name,
        'driver_id': s.driver_id,
        'driver_name': s.driver.name,
        'bus_number': s.driver.bus_number,
        'capacity': s.capacity,
        'days_of_week': sorted(s.weekdays()),
        'departure_time': s.departure_time.strftime('%H:%M'),
        'is_active': s.is_active,
        'start_date': s.start_date.isoformat() if s.start_date else None,
        'end_date': s.end_date.isoformat() if s.end_date else None,
    }


def _clean(d, company, partial):
    """Return (fields, error). Same rules as create_trip."""
    f = {}
    if not partial or 'route_id' in d:
        route = Route.objects.filter(id=_int(d.get('route_id')), company=company).first()
        if not route:
            return None, 'route not found for this company.'
        f['route'] = route
    if not partial or 'driver_id' in d:
        driver = Driver.objects.filter(id=_int(d.get('driver_id')), company=company).first()
        if not driver:
            return None, 'driver not found for this company.'
        f['driver'] = driver
    if not partial or 'capacity' in d:
        cap = _int(d.get('capacity'))
        if cap is None or not 1 <= cap <= 100:
            return None, 'capacity must be between 1 and 100.'
        f['capacity'] = cap
    if not partial or 'days_of_week' in d:
        days = _days(d.get('days_of_week'))
        if days is None:
            return None, 'days_of_week must be a list of weekdays, 0 (Mon) to 6 (Sun).'
        f['days_of_week'] = days
    if not partial or 'departure_time' in d:
        try:
            t = parse_time(str(d.get('departure_time') or ''))
        except ValueError:
            t = None
        if t is None:
            return None, 'departure_time must be HH:MM.'
        f['departure_time'] = t.replace(second=0, microsecond=0)
    for key in ('start_date', 'end_date'):
        if key in d:
            raw = d.get(key)
            if raw in (None, ''):
                f[key] = None
            else:
                try:
                    dt = parse_date(str(raw))
                except ValueError:
                    dt = None
                if dt is None:
                    return None, f'{key} must be YYYY-MM-DD.'
                f[key] = dt
    if 'is_active' in d:
        if not isinstance(d['is_active'], bool):
            return None, 'is_active must be true or false.'
        f['is_active'] = d['is_active']
    return f, None


def _cancel_future_trips(sched):
    """Cancel future generated trips with no bookings or parcels. Returns (cancelled, kept)."""
    now = timezone.now()
    with transaction.atomic():
        ids = list(
            Trip.objects.filter(schedule=sched, status='scheduled', departure_at__gt=now,
                                bookings__isnull=True, parcels__isnull=True)
            .select_for_update(of=('self',)).values_list('id', flat=True))
        cancelled = Trip.objects.filter(id__in=ids, status='scheduled').update(status='cancelled')
        kept = Trip.objects.filter(schedule=sched, status='scheduled', departure_at__gt=now).count()
    return cancelled, kept


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_schedules(request, company_id):
    company = get_object_or_404(Company, id=company_id)
    if not can_manage_company(request.user, company):
        return _bad('You are not authorized to view schedules for this company.', 403)
    qs = (TripSchedule.objects.filter(route__company=company)
          .select_related('route', 'driver').order_by('departure_time', 'id'))
    return Response([_data(s) for s in qs])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_schedule(request):
    company = get_object_or_404(Company, id=_int(request.data.get('company_id')))
    if not can_manage_company(request.user, company):
        return _bad('You are not authorized to create schedules for this company.', 403)
    f, err = _clean(request.data, company, partial=False)
    if err:
        return _bad(err, 404 if 'not found' in err else 400)
    if f.get('start_date') and f.get('end_date') and f['end_date'] < f['start_date']:
        return _bad('end_date cannot be before start_date.')
    if TripSchedule.objects.filter(
            route=f['route'], driver=f['driver'], days_of_week=f['days_of_week'],
            departure_time=f['departure_time']).exists():
        return _bad('An identical schedule already exists.', 409)
    s = TripSchedule.objects.create(**f)
    return Response(_data(s), status=status.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def manage_schedule(request, schedule_id):
    s = get_object_or_404(TripSchedule.objects.select_related('route', 'driver'), id=schedule_id)
    company = s.route.company
    if not can_manage_company(request.user, company):
        return _bad('You are not authorized to manage this schedule.', 403)
    if request.method == 'DELETE':
        cancelled, kept = _cancel_future_trips(s)
        s.delete()
        return Response({'cancelled_trips': cancelled, 'kept_trips': kept})
    f, err = _clean(request.data, company, partial=True)
    if err:
        return _bad(err, 404 if 'not found' in err else 400)
    old = (s.departure_time, s.days_of_week, s.is_active)
    for k, v in f.items():
        setattr(s, k, v)
    if s.start_date and s.end_date and s.end_date < s.start_date:
        return _bad('end_date cannot be before start_date.')
    s.save()
    data = _data(s)
    if (old[2] and not s.is_active) or old[0] != s.departure_time or old[1] != s.days_of_week:
        c, k = _cancel_future_trips(s)
        data['cancelled_trips'] = c
        data['kept_trips'] = k
    resumed = not old[2] and s.is_active
    if s.is_active and (resumed or old[0] != s.departure_time or old[1] != s.days_of_week):
        g = regenerate_for_schedule(s)
        data['generated_trips'] = g['created'] + g['revived']
    return Response(data)
