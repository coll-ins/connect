import logging
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Count, Q, Sum
from django.utils import timezone

from bookings.models import Booking, Incident, Payment

from .models import Trip, TripSchedule

logger = logging.getLogger(__name__)


def _period_bounds(start, end):
    tz = timezone.get_current_timezone()
    start_at = timezone.make_aware(datetime.combine(start, time.min), tz)
    end_at = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz)
    return start_at, end_at


def _group_counts(queryset, field):
    return [
        {'status': row[field], 'count': row['count']}
        for row in queryset.values(field).annotate(count=Count('id')).order_by(field)
    ]


def build_weekly_summary(company, period_start, period_end):
    start_at, end_at = _period_bounds(period_start, period_end)
    trips = Trip.objects.filter(
        route__company=company,
        departure_at__gte=start_at,
        departure_at__lt=end_at,
    )
    bookings = Booking.objects.filter(
        route__company=company,
        created_at__gte=start_at,
        created_at__lt=end_at,
    )
    incidents = Incident.objects.filter(
        trip__route__company=company,
        reported_at__gte=start_at,
        reported_at__lt=end_at,
    )
    payment_groups = Payment.objects.filter(
        booking__route__company=company,
        booking__created_at__gte=start_at,
        booking__created_at__lt=end_at,
    ).values('status').annotate(
        count=Count('id'),
        amount=Sum('amount'),
    ).order_by('status')

    return {
        'trips_by_status': _group_counts(trips, 'status'),
        'bookings_by_status': _group_counts(bookings, 'status'),
        'payments_by_status': [
            {
                'status': row['status'],
                'count': row['count'],
                'amount': str(row['amount'] or 0),
            }
            for row in payment_groups
        ],
        'incidents_by_status': _group_counts(incidents, 'status'),
        'incidents_by_type': [
            {'type': row['incident_type'], 'count': row['count']}
            for row in incidents.values('incident_type')
            .annotate(count=Count('id'))
            .order_by('incident_type')
        ],
        'schedule_generation_issues': [
            {
                'schedule_id': schedule.id,
                'route': schedule.route.name,
                'driver': schedule.driver.name,
                'driver_unavailable': schedule.driver_unavailable_count,
                'driver_conflicts': schedule.driver_conflict_count,
            }
            for schedule in TripSchedule.objects.filter(
                route__company=company,
                is_active=True,
            ).filter(
                Q(driver_unavailable_count__gt=0)
                | Q(driver_conflict_count__gt=0)
            ).select_related('route', 'driver').order_by('route__name', 'id')
        ],
    }


def _report_body(report):
    summary = report.summary

    def lines(key, label):
        rows = summary.get(key, [])
        if not rows:
            return [f'{label}: none']
        return [
            f'{label}: ' + ', '.join(
                f"{row.get('status') or row.get('type')}: {row['count']}"
                for row in rows
            )
        ]

    body = [
        f'{report.company.name} weekly operations report',
        f'Activity period: {report.period_start} through {report.period_end}',
    ]
    if report.renewal_date:
        body.append(f'Manual schedule renewal due: {report.renewal_date}')
    body.extend(lines('trips_by_status', 'Trips'))
    body.extend(lines('bookings_by_status', 'Bookings'))
    body.extend(lines('payments_by_status', 'Payments'))
    body.extend(lines('incidents_by_status', 'Incidents by status'))
    body.extend(lines('incidents_by_type', 'Incidents by type'))
    issues = summary.get('schedule_generation_issues', [])
    body.append(f'Schedule generation issues: {len(issues)} template(s)')
    for issue in issues:
        body.append(
            f"  Route {issue['route']} / template #{issue['schedule_id']}: "
            f"{issue['driver_unavailable']} unavailable, "
            f"{issue['driver_conflicts']} driver conflicts"
        )
    return '\n'.join(body)


def _manager_emails(company):
    emails = set(
        company.users.filter(
            role='company_manager',
            is_active=True,
        ).exclude(email='').values_list('email', flat=True)
    )
    owner = company.user
    if owner and owner.is_active and owner.role == 'company_manager' and owner.email:
        emails.add(owner.email)
    return sorted(emails)


def deliver_report_email(report):
    if report.email_status == 'sent':
        return 'sent'

    recipients = _manager_emails(report.company)
    if not settings.EMAIL_HOST or not settings.DEFAULT_FROM_EMAIL or not recipients:
        report.email_status = 'skipped'
        report.email_error = (
            'Email is not configured or no manager email is available; '
            'the report remains available in the app.'
        )
        report.save(update_fields=['email_status', 'email_error'])
        return 'skipped'

    try:
        sent = send_mail(
            subject=f'{report.company.name}: weekly operations report',
            message=_report_body(report),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
        if sent != 1:
            raise RuntimeError('Email backend did not confirm delivery.')
    except Exception:
        logger.exception('weekly operations report email failed for report %s', report.pk)
        report.email_status = 'failed'
        report.email_error = 'Email delivery failed. The report is available in the app and will be retried.'
        report.save(update_fields=['email_status', 'email_error'])
        return 'failed'

    report.email_status = 'sent'
    report.email_error = ''
    report.email_sent_at = timezone.now()
    report.save(update_fields=['email_status', 'email_error', 'email_sent_at'])
    return 'sent'
