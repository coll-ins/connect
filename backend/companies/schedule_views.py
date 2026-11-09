import logging
from datetime import timedelta

from django.db import models, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from buses.models import Bus
from drivers.models import Driver
from users.permissions import can_access_company
from users.route_scope import operator_route_ids

from .models import Company, Route, Trip, TripSchedule, WeeklyOperationsReport
from .trip_generation import regenerate_for_schedule
from .views import can_manage_company


TIME_FIELDS = ('departure_time', 'service_end_time', 'rush_start_time', 'rush_end_time')
GENERATION_FIELDS = (
    'route_id', 'driver_id', 'days_of_week', 'departure_time',
    'service_end_time', 'normal_interval_minutes', 'rush_interval_minutes',
    'rush_start_time', 'rush_end_time', 'auto_renew',
)


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
        'bus_id': s.bus_id,
        'bus_number': s.bus.bus_number if s.bus_id else s.driver.bus_number,
        'bus_plate': s.bus.registration_number if s.bus_id else None,
        'vehicle_type': s.bus.get_vehicle_type_display() if s.bus_id else None,
        'capacity': s.capacity,
        'days_of_week': sorted(s.weekdays()),
        'departure_time': s.departure_time.strftime('%H:%M'),
        'service_end_time': s.service_end_time.strftime('%H:%M') if s.service_end_time else None,
        'normal_interval_minutes': s.normal_interval_minutes,
        'rush_interval_minutes': s.rush_interval_minutes,
        'rush_start_time': s.rush_start_time.strftime('%H:%M') if s.rush_start_time else None,
        'rush_end_time': s.rush_end_time.strftime('%H:%M') if s.rush_end_time else None,
        'auto_renew': s.auto_renew,
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
    if not partial or 'bus_id' in d:
        # Seats come from the bus; a 'capacity' in the request is ignored.
        raw = d.get('bus_id')
        whole = not isinstance(raw, bool) and str(raw).strip().isdigit()
        bus = whole and Bus.objects.filter(
            id=int(str(raw).strip()), company=company,
            is_active=True, maintenance_status='operational',
        ).first()
        if not bus:
            return None, 'bus not found for this company, or it is not in service.'
        f['bus'] = bus
        f['capacity'] = bus.capacity
    if not partial or 'days_of_week' in d:
        days = _days(d.get('days_of_week'))
        if days is None:
            return None, 'days_of_week must be a list of weekdays, 0 (Mon) to 6 (Sun).'
        f['days_of_week'] = days
    for key in TIME_FIELDS:
        if (not partial and key == 'departure_time') or key in d:
            raw = d.get(key)
            if key != 'departure_time' and raw in (None, ''):
                f[key] = None
                continue
            try:
                value = parse_time(str(raw or ''))
            except ValueError:
                value = None
            if value is None:
                return None, f'{key} must be HH:MM.'
            f[key] = value.replace(second=0, microsecond=0)
    for key in ('normal_interval_minutes', 'rush_interval_minutes'):
        if not partial or key in d:
            interval = _int(d.get(key, 60 if key == 'normal_interval_minutes' else 30))
            if interval is None or not 15 <= interval <= 240:
                return None, f'{key} must be between 15 and 240 minutes.'
            f[key] = interval
    if not partial or 'auto_renew' in d:
        auto_renew = d.get('auto_renew', False)
        if not isinstance(auto_renew, bool):
            return None, 'auto_renew must be true or false.'
        f['auto_renew'] = auto_renew
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


def _validate_template(s, fields):
    value = lambda key: fields.get(key, getattr(s, key))
    if value('rush_interval_minutes') > value('normal_interval_minutes'):
        return 'rush_interval_minutes cannot exceed normal_interval_minutes.'
    start = value('departure_time')
    end = value('service_end_time')
    rush_start = value('rush_start_time')
    rush_end = value('rush_end_time')
    if (rush_start is None) != (rush_end is None):
        return 'Both rush-hour window times are required.'
    if end is not None and end <= start:
        return 'service_end_time must be later than departure_time.'
    if rush_start is not None:
        if end is None:
            return 'A service end time is required when a rush-hour window is set.'
        if not start <= rush_start < rush_end <= end:
            return 'Rush-hour times must fall within the service window.'
    auto_renew = value('auto_renew')
    start_date = fields.get('start_date', s.start_date)
    end_date = fields.get('end_date', s.end_date)
    if not auto_renew:
        if start_date is None or end_date is None:
            return 'Manual renewal requires a start date and an end date.'
        if end_date < start_date:
            return 'end_date cannot be before start_date.'
        if (end_date - start_date).days > 6:
            return 'Manual service windows cannot exceed one week.'
    elif start_date and end_date and end_date < start_date:
        return 'end_date cannot be before start_date.'
    return None


logger = logging.getLogger(__name__)


def _generate_on_create(sched):
    """Generate initial trips, propagating failures so schedule creation can roll back."""
    g = regenerate_for_schedule(sched)
    if g['invalid']:
        raise ValueError(f'schedule {sched.pk} is invalid for trip generation')
    return g['created'] + g['revived']


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
          .select_related('route', 'driver', 'bus').order_by('departure_time', 'id'))
    return Response([_data(s) for s in qs])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_generation_exceptions(request, company_id):
    company = get_object_or_404(Company, id=company_id)
    if not can_access_company(request.user, company.id):
        return _bad('You are not authorized to view schedule exceptions for this company.', 403)
    qs = TripSchedule.objects.filter(
        route__company=company,
        is_active=True,
    ).filter(
        models.Q(driver_unavailable_count__gt=0)
        | models.Q(driver_conflict_count__gt=0)
    ).select_related('route', 'driver', 'bus').order_by('route__name', 'departure_time', 'id')
    if request.user.role == 'company_operator':
        route_ids = operator_route_ids(request.user)
        if route_ids is not None:
            qs = qs.filter(route_id__in=route_ids)
    return Response([
        {
            'schedule_id': s.id,
            'route_id': s.route_id,
            'route_name': s.route.name,
            'departure_time': s.departure_time.strftime('%H:%M'),
            'service_end_time': (
                s.service_end_time.strftime('%H:%M') if s.service_end_time else None
            ),
            'driver_id': s.driver_id,
            'driver_name': s.driver.name,
            'driver_unavailable_count': s.driver_unavailable_count,
            'driver_conflict_count': s.driver_conflict_count,
            'checked_at': (
                s.generation_checked_at.isoformat()
                if s.generation_checked_at else None
            ),
        }
        for s in qs
    ])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_weekly_reports(request, company_id):
    company = get_object_or_404(Company, id=company_id)
    if not can_manage_company(request.user, company):
        return _bad('You are not authorized to view reports for this company.', 403)
    reports = WeeklyOperationsReport.objects.filter(company=company)[:26]
    return Response([
        {
            'id': report.id,
            'report_type': report.report_type,
            'period_start': report.period_start.isoformat(),
            'period_end': report.period_end.isoformat(),
            'renewal_date': (
                report.renewal_date.isoformat() if report.renewal_date else None
            ),
            'summary': report.summary,
            'email_status': report.email_status,
            'email_error': report.email_error,
            'created_at': report.created_at.isoformat(),
            'email_sent_at': (
                report.email_sent_at.isoformat() if report.email_sent_at else None
            ),
        }
        for report in reports
    ])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_schedule(request):
    company = get_object_or_404(Company, id=_int(request.data.get('company_id')))
    if not can_manage_company(request.user, company):
        return _bad('You are not authorized to create schedules for this company.', 403)
    f, err = _clean(request.data, company, partial=False)
    if err:
        return _bad(err, 404 if 'not found' in err else 400)
    candidate = TripSchedule(**f)
    err = _validate_template(candidate, f)
    if err:
        return _bad(err)
    try:
        with transaction.atomic():
            Company.objects.select_for_update().get(pk=company.pk)
            duplicate_fields = {
                'route': f['route'],
                'driver': f['driver'],
                'bus': f['bus'],
                'days_of_week': f['days_of_week'],
                'departure_time': f['departure_time'],
                'service_end_time': f.get('service_end_time'),
                'normal_interval_minutes': f['normal_interval_minutes'],
                'rush_interval_minutes': f['rush_interval_minutes'],
                'rush_start_time': f.get('rush_start_time'),
                'rush_end_time': f.get('rush_end_time'),
                'auto_renew': f['auto_renew'],
                'start_date': f.get('start_date'),
                'end_date': f.get('end_date'),
            }
            if TripSchedule.objects.filter(**duplicate_fields).exists():
                return _bad('An identical schedule already exists.', 409)
            s = TripSchedule.objects.create(**f)
            generated = _generate_on_create(s) if s.is_active else None
    except Exception:
        logger.exception('schedule creation failed for company %s', company.pk)
        return _bad(
            'Schedule creation failed because its trips could not be generated.',
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    data = _data(s)
    if s.is_active:
        data['generated_trips'] = generated
    return Response(data, status=status.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def manage_schedule(request, schedule_id):
    s = get_object_or_404(
        TripSchedule.objects.select_related('route', 'driver'), id=schedule_id)
    company = s.route.company
    if not can_manage_company(request.user, company):
        return _bad('You are not authorized to manage this schedule.', 403)
    if request.method == 'DELETE':
        cancelled, kept = _cancel_future_trips(s)
        s.delete()
        return Response({'cancelled_trips': cancelled, 'kept_trips': kept})
    with transaction.atomic():
        s = TripSchedule.objects.select_for_update().select_related('route', 'driver').get(pk=schedule_id)
        f, err = _clean(request.data, company, partial=True)
        if err:
            return _bad(err, 404 if 'not found' in err else 400)
        err = _validate_template(s, f)
        if err:
            return _bad(err)
        old_fields = {key: getattr(s, key) for key in GENERATION_FIELDS}
        old_bus_id = s.bus_id
        old_start, old_end, old_active = s.start_date, s.end_date, s.is_active
        for key, value in f.items():
            setattr(s, key, value)
        s.save()
        config_changed = any(old_fields[key] != getattr(s, key) for key in GENERATION_FIELDS)
        if old_bus_id != s.bus_id:
            # Move only the empty future trips; a trip with bookings keeps its
            # bus until someone swaps it on purpose (seat checks run there).
            empty = Trip.objects.filter(
                schedule=s,
                status='scheduled',
                departure_at__gt=timezone.now(),
                bookings__isnull=True,
                parcels__isnull=True,
            ).exclude(
                departure_at__in=s.bus.trips.filter(
                    status__in=('scheduled', 'boarding', 'departed'),
                ).exclude(schedule=s).values('departure_at'),
            )
            with transaction.atomic():
                # Lock first, then re-check: a booking or a blocked seat may
                # have landed since the query above was planned.
                ids = list(empty.select_for_update(of=('self',)).values_list('id', flat=True))
                Trip.objects.filter(
                    id__in=ids, bookings__isnull=True, parcels__isnull=True,
                ).exclude(
                    seat_assignments__seat_no__gt=s.capacity,
                ).update(bus=s.bus, capacity=s.capacity)
        date_changed = old_start != s.start_date or old_end != s.end_date
        date_window_expanded = (
            date_changed
            and (old_start is None or (s.start_date is not None and s.start_date <= old_start))
            and (old_end is None or (s.end_date is not None and s.end_date >= old_end))
        )
        if (
            date_changed and old_end and s.end_date
            and s.end_date > old_end
            and s.start_date == old_end + timedelta(days=1)
        ):
            date_window_expanded = True
        should_cancel = (
            (old_active and not s.is_active)
            or config_changed
            or (date_changed and not date_window_expanded)
        )
        if should_cancel:
            cancelled, kept = _cancel_future_trips(s)
        else:
            cancelled, kept = 0, 0
        data = _data(s)
        if should_cancel:
            data['cancelled_trips'] = cancelled
            data['kept_trips'] = kept
        should_generate = s.is_active and (
            (not old_active) or config_changed or date_changed
        )
        if should_generate:
            g = regenerate_for_schedule(s)
            data['generated_trips'] = g['created'] + g['revived']
        return Response(data)
