from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from companies.models import Company, Route, Trip
from drivers.models import Driver

User = get_user_model()
TIMETABLE_URL = '/api/drivers/me/timetable/'


class DriverTimetableTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Timetable Coaches',
            areas_served='Nairobi',
        )
        self.route = Route.objects.create(
            company=self.company,
            name='CBD to Westlands',
            start_point='CBD',
            end_point='Westlands',
            price='100.00',
        )
        self.driver = Driver.objects.create(
            name='Own Driver',
            phone_number='+254712345678',
            bus_number='KAA 001A',
            company=self.company,
        )
        self.driver_user = User.objects.create_user(
            username='timetable_driver',
            password='test-password',
            phone_number='+254712345678',
            role='driver',
            company=self.company,
        )

    def create_trip(self, driver, departure_at, status_value='scheduled'):
        return Trip.objects.create(
            route=self.route,
            driver=driver,
            departure_at=departure_at,
            capacity=30,
            status=status_value,
        )

    def test_driver_gets_own_assigned_trips_for_seven_local_days(self):
        today = timezone.localdate()
        local_midnight = timezone.make_aware(
            datetime.combine(today, time.min)
        )
        today_trip = self.create_trip(
            self.driver,
            local_midnight + timedelta(hours=8),
        )
        cancelled_trip = self.create_trip(
            self.driver,
            local_midnight + timedelta(days=1, hours=9),
            status_value='cancelled',
        )
        last_day_trip = self.create_trip(
            self.driver,
            local_midnight + timedelta(days=6, hours=10),
        )
        self.create_trip(
            self.driver,
            local_midnight + timedelta(days=7, hours=11),
        )
        self.create_trip(
            self.driver,
            local_midnight - timedelta(minutes=1),
        )
        coworker = Driver.objects.create(
            name='Coworker',
            phone_number='+254712345679',
            bus_number='KBB 002B',
            company=self.company,
        )
        self.create_trip(coworker, local_midnight + timedelta(hours=12))

        self.client.force_authenticate(self.driver_user)
        response = self.client.get(TIMETABLE_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [trip['id'] for trip in response.data['trips']],
            [today_trip.id, cancelled_trip.id, last_day_trip.id],
        )
        self.assertEqual(response.data['start_date'], today.isoformat())
        self.assertEqual(
            response.data['end_date'],
            (today + timedelta(days=6)).isoformat(),
        )
        self.assertEqual(response.data['trips'][0]['route_name'], self.route.name)
        self.assertEqual(response.data['trips'][0]['bus_number'], self.driver.bus_number)
        self.assertEqual(response.data['trips'][1]['status'], 'cancelled')

    def test_timetable_requires_driver_account(self):
        passenger = User.objects.create_user(
            username='timetable_passenger',
            password='test-password',
            phone_number='+254700000001',
            role='passenger',
        )
        self.client.force_authenticate(passenger)

        response = self.client.get(TIMETABLE_URL)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_timetable_requires_a_linked_driver_profile(self):
        unlinked_driver = User.objects.create_user(
            username='unlinked_driver',
            password='test-password',
            phone_number='+254712345699',
            role='driver',
            company=self.company,
        )
        self.client.force_authenticate(unlinked_driver)

        response = self.client.get(TIMETABLE_URL)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
