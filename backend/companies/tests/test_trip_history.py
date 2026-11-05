from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from rest_framework.test import APIClient

from companies.models import Company, Route, Trip
from drivers.models import Driver


User = get_user_model()


class TripHistoryVisibilityTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='History Company',
            areas_served='Nairobi',
        )
        self.route = Route.objects.create(
            company=self.company,
            name='Nairobi to Mombasa',
            start_point='Nairobi',
            end_point='Mombasa',
            price=Decimal('1000.00'),
        )
        self.driver = Driver.objects.create(
            name='History Driver',
            phone_number='0700000011',
            bus_number='KCA 123A',
            company=self.company,
        )
        now = timezone.now()
        self.old_trip = Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=now - timedelta(days=31),
            capacity=30,
            status='completed',
        )
        self.recent_trip = Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=now - timedelta(days=29),
            capacity=30,
            status='completed',
        )
        self.client = APIClient()
        self.url = reverse(
            'get_company_trips',
            kwargs={'company_id': self.company.pk},
        )

    def make_staff(self, role):
        return User.objects.create_user(
            username=f'{role}_history',
            password='test-password',
            phone_number=f'+254700000{User.objects.count():03d}',
            role=role,
            company=self.company,
        )

    def test_manager_and_operator_only_receive_recent_operational_history(self):
        expected = {self.recent_trip.pk}
        for role in ('company_manager', 'company_operator'):
            with self.subTest(role=role):
                self.client.force_authenticate(self.make_staff(role))
                response = self.client.get(self.url)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    {trip['id'] for trip in response.data},
                    expected,
                )

        self.assertTrue(Trip.objects.filter(pk=self.old_trip.pk).exists())

    def test_auditor_retains_full_trip_history_and_review_fields(self):
        self.client.force_authenticate(self.make_staff('company_auditor'))
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        trips_by_id = {trip['id']: trip for trip in response.data}
        old_trip = trips_by_id[self.old_trip.pk]
        self.assertEqual(old_trip['driver_name'], 'History Driver')
        self.assertEqual(old_trip['driver_bus_number'], 'KCA 123A')
        self.assertEqual(
            old_trip['route_details']['name'],
            'Nairobi to Mombasa',
        )
        self.assertEqual(
            parse_datetime(old_trip['departure_at']),
            self.old_trip.departure_at,
        )

    def test_direct_trip_details_respect_operational_history_cutoff(self):
        for role in ('company_manager', 'company_operator'):
            with self.subTest(role=role):
                self.client.force_authenticate(self.make_staff(role))
                old_response = self.client.get(
                    reverse(
                        'get_trip_details',
                        kwargs={'trip_id': self.old_trip.pk},
                    )
                )
                recent_response = self.client.get(
                    reverse(
                        'get_trip_details',
                        kwargs={'trip_id': self.recent_trip.pk},
                    )
                )

                self.assertEqual(old_response.status_code, 404)
                self.assertEqual(recent_response.status_code, 200)

        self.client.force_authenticate(self.make_staff('company_auditor'))
        auditor_response = self.client.get(
            reverse(
                'get_trip_details',
                kwargs={'trip_id': self.old_trip.pk},
            )
        )
        self.assertEqual(auditor_response.status_code, 200)
        self.assertTrue(Trip.objects.filter(pk=self.old_trip.pk).exists())
