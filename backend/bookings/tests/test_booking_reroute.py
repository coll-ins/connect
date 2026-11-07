from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import BoardingEvent, Booking
from companies.models import Company, PickupStage, Route, Trip
from companies.routing import RoutingError
from drivers.models import Driver

User = get_user_model()
LINE = {'type': 'LineString', 'coordinates': [[36.82, -1.29], [36.83, -1.28]]}


class BookingRerouteTests(APITestCase):
    def setUp(self):
        cache.clear()
        company = Company.objects.create(name='A', description='d', areas_served='N')
        self.route = Route.objects.create(
            company=company, name='R', start_point='CBD', end_point='Ngong',
            price=Decimal('100.00'),
            end_latitude=Decimal('-1.36'), end_longitude=Decimal('36.65'),
        )
        self.stage = PickupStage.objects.create(
            route=self.route, name='S1', latitude=Decimal('-1.285'),
            longitude=Decimal('36.82'), order=1,
        )
        self.driver = Driver.objects.create(
            name='D', phone_number='0700000001', bus_number='K1', company=company,
            latitude=Decimal('-1.29'), longitude=Decimal('36.83'),
            location_updated_at=timezone.now(),
        )
        self.trip = Trip.objects.create(
            route=self.route, driver=self.driver, capacity=10, status='departed',
            departure_at=timezone.now() + timedelta(minutes=5),
        )
        self.owner = User.objects.create_user(
            username='own', password='x', phone_number='0711000001',
        )
        self.stranger = User.objects.create_user(
            username='str', password='x', phone_number='0711000002',
        )
        self.booking = Booking.objects.create(
            user=self.owner, route=self.route, trip=self.trip, driver=self.driver,
            pickup_stage=self.stage, pickup_location='S1', seats=1,
            total_amount=Decimal('100.00'), status='confirmed',
        )
        self.client.force_authenticate(user=self.owner)

    def get(self, goal='pickup'):
        return self.client.get(f'/api/bookings/{self.booking.id}/reroute/?goal={goal}')

    @patch('companies.routing.road_line', return_value=(LINE, 1500.4))
    def test_routes_from_the_bus_to_the_pickup_stage(self, road_line):
        resp = self.get()

        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['geometry'], LINE)
        self.assertEqual(resp.json()['distance_m'], 1500)
        self.assertEqual(resp.json()['goal'], 'pickup')
        self.assertEqual(
            road_line.call_args.args[0], [(-1.29, 36.83), (-1.285, 36.82)],
        )

    @patch('companies.routing.road_line', return_value=(LINE, 900.0))
    def test_routes_to_the_end_of_the_route_after_pickup(self, road_line):
        self.assertEqual(self.get('destination').status_code, 200)
        self.assertEqual(road_line.call_args.args[0][1], (-1.36, 36.65))

    @patch('companies.routing.road_line', return_value=(LINE, 900.0))
    def test_nearby_requests_share_one_road_service_call(self, road_line):
        self.get()
        self.get()
        self.assertEqual(road_line.call_count, 1)

    @patch('companies.routing.road_line', return_value=(LINE, 900.0))
    def test_refuses_anyone_who_does_not_own_the_booking(self, road_line):
        self.client.force_authenticate(user=self.stranger)
        self.assertEqual(self.get().status_code, 403)
        road_line.assert_not_called()

    @patch('companies.routing.road_line', return_value=(LINE, 900.0))
    def test_refuses_an_unknown_goal(self, road_line):
        self.assertEqual(self.get('anywhere').status_code, 400)
        road_line.assert_not_called()

    @patch('companies.routing.road_line', return_value=(LINE, 900.0))
    def test_refuses_a_trip_that_is_not_live(self, road_line):
        self.trip.status = 'scheduled'
        self.trip.save(update_fields=['status'])
        self.assertEqual(self.get().status_code, 409)
        road_line.assert_not_called()

    @patch('companies.routing.road_line', return_value=(LINE, 900.0))
    def test_refuses_stale_driver_gps(self, road_line):
        Driver.objects.filter(pk=self.driver.pk).update(
            location_updated_at=timezone.now() - timedelta(hours=1),
        )
        self.assertEqual(self.get().status_code, 409)
        road_line.assert_not_called()

    @patch('companies.routing.road_line', side_effect=RoutingError('down'))
    def test_reports_when_the_road_service_is_down(self, _road_line):
        self.assertEqual(self.get().status_code, 503)

    def test_live_location_says_whether_the_passenger_has_boarded(self):
        url = f'/api/bookings/{self.booking.id}/live-location/'
        self.assertIs(self.client.get(url).json()['boarded'], False)

        BoardingEvent.objects.create(
            booking=self.booking, trip=self.trip, method='pin',
        )
        self.assertIs(self.client.get(url).json()['boarded'], True)
