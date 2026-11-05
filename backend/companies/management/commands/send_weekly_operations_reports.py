from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from companies.models import Company, TripSchedule, WeeklyOperationsReport
from companies.weekly_reports import build_weekly_summary, deliver_report_email


class Command(BaseCommand):
    help = 'Create weekly operations reports and send them before schedule renewal.'

    def handle(self, *args, **options):
        today = timezone.localdate()
        attempted = 0
        email_failures = 0

        if today.weekday() == 0:
            period_start = today - timedelta(days=7)
            period_end = today - timedelta(days=1)
            company_ids = TripSchedule.objects.filter(
                is_active=True,
                auto_renew=True,
            ).values_list('route__company_id', flat=True).distinct()
            for company in Company.objects.filter(id__in=company_ids).select_related('user'):
                report, _ = WeeklyOperationsReport.objects.get_or_create(
                    company=company,
                    report_type='weekly',
                    period_start=period_start,
                    defaults={
                        'period_end': period_end,
                        'summary': build_weekly_summary(company, period_start, period_end),
                    },
                )
                attempted += 1
                email_failures += deliver_report_email(report) == 'failed'

        renewal_date = today + timedelta(days=1)
        manual_schedule_company_ids = TripSchedule.objects.filter(
            is_active=True,
            auto_renew=False,
            end_date=renewal_date,
        ).values_list('route__company_id', flat=True).distinct()
        period_start = today - timedelta(days=6)
        for company in Company.objects.filter(
            id__in=manual_schedule_company_ids,
        ).select_related('user'):
            report, _ = WeeklyOperationsReport.objects.get_or_create(
                company=company,
                report_type='manual_renewal',
                period_start=period_start,
                defaults={
                    'period_end': today,
                    'renewal_date': renewal_date,
                    'summary': build_weekly_summary(company, period_start, today),
                },
            )
            attempted += 1
            email_failures += deliver_report_email(report) == 'failed'

        retry_reports = WeeklyOperationsReport.objects.filter(
            email_status__in=('failed', 'skipped'),
            created_at__date__gte=today - timedelta(days=14),
            created_at__date__lt=today,
        ).select_related('company', 'company__user')
        for report in retry_reports:
            attempted += 1
            email_failures += deliver_report_email(report) == 'failed'

        self.stdout.write(
            f'weekly operations reports: {attempted} processed, '
            f'{email_failures} email delivery failure(s)'
        )
        if email_failures:
            raise CommandError(
                f'{email_failures} report email(s) failed; failures are visible in-app and will be retried.'
            )
