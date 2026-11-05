from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking, Incident, Payment
from companies.models import (
    Company,
    Route,
    Trip,
    TripSchedule,
    WeeklyOperationsReport,
)
from companies.weekly_reports import build_weekly_summary
from drivers.models import Driver

User = get_user_model()
NAIROBI = ZoneInfo('Africa/Nairobi')


class WeeklyOperationsReportTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Weekly Report Company',
            areas_served='Nairobi',
        )
        self.manager = User.objects.create_user(
            username='weekly_report_manager',
            password='test-password',
            phone_number='+254700000221',
            email='manager@example.com',
            role='company_manager',
            company=self.company,
        )
        self.route = Route.objects.create(
            company=self.company,
            name='Nairobi to Naivasha',
            start_point='Nairobi',
            end_point='Naivasha',
            price=Decimal('500.00'),
        )
        self.driver = Driver.objects.create(
            name='Weekly Report Driver',
            phone_number='+254700000222',
            bus_number='KCA 222A',
            company=self.company,
        )

    def make_schedule(self, **overrides):
        values = {
            'route': self.route,
            'driver': self.driver,
            'capacity': 30,
            'days_of_week': '0,1,2,3,4,5,6',
            'departure_time': time(7, 0),
            'auto_renew': True,
        }
        values.update(overrides)
        return TripSchedule.objects.create(**values)

    def test_weekly_command_is_idempotent_and_sends_one_email(self):
        self.make_schedule()
        monday = date(2030, 1, 7)
        with override_settings(
            EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
            EMAIL_HOST='smtp.example.test',
            DEFAULT_FROM_EMAIL='reports@example.test',
        ), mock.patch(
            'companies.management.commands.send_weekly_operations_reports.timezone.localdate',
            return_value=monday,
        ):
            call_command('send_weekly_operations_reports')
            call_command('send_weekly_operations_reports')

        report = WeeklyOperationsReport.objects.get(company=self.company)
        self.assertEqual(report.report_type, 'weekly')
        self.assertEqual(report.period_start, monday - timedelta(days=7))
        self.assertEqual(report.period_end, monday - timedelta(days=1))
        self.assertEqual(report.email_status, 'sent')
        self.assertEqual(len(mail.outbox), 1)

    def test_manual_schedule_report_is_created_before_renewal(self):
        today = date(2030, 1, 8)
        renewal = today + timedelta(days=1)
        self.make_schedule(
            auto_renew=False,
            start_date=today - timedelta(days=5),
            end_date=renewal,
        )
        with mock.patch(
            'companies.management.commands.send_weekly_operations_reports.timezone.localdate',
            return_value=today,
        ):
            call_command('send_weekly_operations_reports')

        report = WeeklyOperationsReport.objects.get(company=self.company)
        self.assertEqual(report.report_type, 'manual_renewal')
        self.assertEqual(report.renewal_date, renewal)
        self.assertEqual(report.email_status, 'skipped')
        self.assertIn('available in the app', report.email_error)

    def test_email_failure_is_visible_and_command_reports_failure(self):
        self.make_schedule()
        monday = date(2030, 1, 7)
        with override_settings(
            EMAIL_HOST='smtp.example.test',
            DEFAULT_FROM_EMAIL='reports@example.test',
        ), mock.patch(
            'companies.management.commands.send_weekly_operations_reports.timezone.localdate',
            return_value=monday,
        ), mock.patch(
            'companies.weekly_reports.send_mail',
            side_effect=OSError('smtp unavailable'),
        ):
            with self.assertRaises(CommandError):
                call_command('send_weekly_operations_reports')

        report = WeeklyOperationsReport.objects.get(company=self.company)
        self.assertEqual(report.email_status, 'failed')
        self.assertIn('will be retried', report.email_error)
        self.assertNotIn('smtp unavailable', report.email_error)

    def test_summary_includes_trip_booking_incident_and_payment_counts(self):
        now = timezone.now()
        trip = Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=now,
            capacity=30,
            status='completed',
        )
        passenger = User.objects.create_user(
            username='weekly_report_passenger',
            password='test-password',
            phone_number='+254700000223',
        )
        booking = Booking.objects.create(
            user=passenger,
            route=self.route,
            trip=trip,
            driver=self.driver,
            pickup_location='Nairobi',
            seats=1,
            total_amount=Decimal('500.00'),
            status='completed',
        )
        Payment.objects.create(
            booking=booking,
            amount=Decimal('500.00'),
            method='digital',
            status='confirmed',
        )
        Incident.objects.create(
            trip=trip,
            reported_by=self.manager,
            incident_type='road_blocked',
            description='Reported road closure.',
        )
        today = timezone.localdate()
        summary = build_weekly_summary(
            self.company,
            today - timedelta(days=1),
            today + timedelta(days=1),
        )

        self.assertEqual(summary['trips_by_status'], [{'status': 'completed', 'count': 1}])
        self.assertEqual(summary['bookings_by_status'], [{'status': 'completed', 'count': 1}])
        self.assertEqual(summary['payments_by_status'][0]['status'], 'confirmed')
        self.assertEqual(summary['incidents_by_type'], [{'type': 'road_blocked', 'count': 1}])

    def test_only_company_manager_can_read_weekly_reports(self):
        report = WeeklyOperationsReport.objects.create(
            company=self.company,
            report_type='weekly',
            period_start=date(2030, 1, 1),
            period_end=date(2030, 1, 7),
            summary={'trips_by_status': []},
        )
        client = APIClient()
        client.force_authenticate(self.manager)
        response = client.get(
            reverse(
                'list_weekly_operations_reports',
                kwargs={'company_id': self.company.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]['id'], report.id)

        operator = User.objects.create_user(
            username='weekly_report_operator',
            password='test-password',
            phone_number='+254700000224',
            role='company_operator',
            company=self.company,
        )
        client.force_authenticate(operator)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            client.get(
                reverse(
                    'list_weekly_operations_reports',
                    kwargs={'company_id': self.company.pk},
                )
            ).status_code,
            403,
        )
