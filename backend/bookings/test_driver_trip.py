from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from companies.models import Company, Route, Trip
from drivers.models import Driver

User = get_user_model()


class DriverStaleTripTests(APITestCase):

    def setUp(self):
        co = Company.objects.create(name='A Line', areas_served='X')
        self.driver = Driver.objects.create(
            company=co, name='D', phone_number='+254712200001', bus_number='KA 1')
        self.user = User.objects.create_user(
            username='dd', password='x', phone_number='+254712200001', role='driver', company=co)
        self.route = Route.objects.create(company=co, name='R', price=Decimal('500'))
        self.client.force_authenticate(self.user)

    def trip(self, status, hours_ago):
        return Trip.objects.create(
            route=self.route, driver=self.driver, status=status, capacity=5,
            departure_at=timezone.now() - timedelta(hours=hours_ago))

    def active(self):
        r = self.client.get(f'/api/bookings/driver/{self.driver.id}/')
        self.assertEqual(r.status_code, 200)
        return r.data['active_trip']

    def test_old_boarding_trip_is_dropped(self):
        self.trip('boarding', 30)
        self.assertIsNone(self.active())

    def test_old_departed_trip_is_dropped(self):
        self.trip('departed', 13)
        self.assertIsNone(self.active())

    def test_recent_boarding_trip_is_kept(self):
        self.trip('boarding', 1)
        self.assertIsNotNone(self.active())
