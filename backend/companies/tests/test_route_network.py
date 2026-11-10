"""The shipped route network: real roads, stages on the line, a way back for
every route, and nobody boarding where the trip ends."""
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking
from companies.geo import line_health, locate_on_line
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

DATA = Path(__file__).resolve().parent.parent / 'data' / 'route_network.json'
NETWORK = json.loads(DATA.read_text())


class RouteNetworkDataTests(TestCase):
    def test_every_stage_sits_on_its_road_line_in_travel_order(self):
        for item in NETWORK:
            geometry = {'type': 'LineString', 'coordinates': item['line']}
            label = f"{item['company']} {item['name']}"
            self.assertGreaterEqual(len(item['stages']), 2, label)
            last = -1.0
            for name, lat, lng in item['stages']:
                offset, along = locate_on_line(geometry, lat, lng)
                self.assertLess(offset, 10, f'{label}: {name} is {offset:.0f} m off the road')
                self.assertGreater(along, last, f'{label}: {name} is out of order')
                last = along

    def test_city_lines_never_turn_back_at_a_terminus(self):
        """A router leaves a drive-past-and-come-back stub when a stage sits
        across a divided road. One sharp junction mid-route is a real road."""
        for item in NETWORK:
            if item['start_point'] == 'Nairobi' or item['end_point'] == 'Nairobi':
                continue  # long distance: highway hairpins are real
            geometry = {'type': 'LineString', 'coordinates': item['line']}
            label = f"{item['company']} {item['name']}"
            health = line_health(geometry, [])
            self.assertLessEqual(health['spurs'], 1, label)
            length = health['length_km'] * 1000
            for lat, lng in health['spur_points']:
                along = locate_on_line(geometry, lat, lng)[1]
                self.assertTrue(1000 < along < length - 1000, label)

    def test_every_route_has_the_same_road_back(self):
        self.assertEqual(len(NETWORK) % 2, 0)
        for out, back in zip(NETWORK[::2], NETWORK[1::2]):
            self.assertEqual(out['company'], back['company'])
            self.assertEqual((out['start_point'], out['end_point']),
                             (back['end_point'], back['start_point']))
            # The stage a trip ends at is the stage the trip back starts from.
            self.assertEqual(out['stages'][-1][0], back['stages'][0][0])
            self.assertEqual(out['stages'][0][0], back['stages'][-1][0])


class RouteNetworkInstalledTests(TestCase):
    def test_ngong_runs_both_ways_from_the_real_stages(self):
        company = Company.objects.get(name='Supermetro')
        out = Route.objects.get(company=company, name='CBD to Ngong')
        back = Route.objects.get(company=company, name='Ngong to CBD')
        names = lambda r: list(  # noqa: E731
            r.pickup_stages.filter(is_active=True).values_list('name', flat=True))
        self.assertEqual(names(out)[0], 'Super Metro Stage, Archives')
        self.assertEqual(names(out)[-1], 'Ngong Matatu Terminus')
        self.assertEqual(names(back)[0], 'Ngong Matatu Terminus')
        self.assertEqual(names(back)[-1], 'Super Metro Stage, Archives')
        self.assertEqual(back.price, out.price)
        self.assertEqual(line_health(back.geometry, [])['spurs'], 0)

    def test_kisumu_stops_at_the_towns_on_the_highway(self):
        route = Route.objects.get(company__name='Supermetro', name='Nairobi to Kisumu')
        names = list(route.pickup_stages.filter(is_active=True).values_list('name', flat=True))
        self.assertEqual(names[1:-1], ['Naivasha', 'Gilgil', 'Nakuru', 'Kericho', 'Awasi', 'Ahero'])

    def test_the_way_back_is_listed_under_the_way_out(self):
        user = get_user_model().objects.create_user(
            username='pax_net', password='password123', phone_number='+254700000971')
        client = APIClient()
        client.force_authenticate(user=user)
        company = Company.objects.get(name='Supermetro')
        resp = client.get(reverse('get_company_routes', kwargs={'company_id': company.id}))
        self.assertEqual(resp.status_code, 200)
        names = [r['name'] for r in resp.data]
        self.assertEqual(names.index('Ngong to CBD'), names.index('CBD to Ngong') + 1)
        self.assertEqual(names.index('Rongai to CBD'), names.index('CBD to Rongai') + 1)


class DestinationIsNotABoardingStageTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Net SACCO')
        self.route = Route.objects.create(
            company=self.company, name='A to C', start_point='A', end_point='C',
            price=Decimal('100.00'))
        self.first, self.mid, self.last = [
            PickupStage.objects.create(
                route=self.route, name=name, order=order,
                latitude=-1.28 - order / 100, longitude=36.82)
            for order, name in enumerate(('A', 'B', 'C'), start=1)
        ]
        driver = Driver.objects.create(
            name='Net Driver', phone_number='+254700000972',
            bus_number='KDN 001A', company=self.company)
        self.trip = Trip.objects.create(
            route=self.route, driver=driver, capacity=14, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=2))
        self.user = get_user_model().objects.create_user(
            username='pax_dest', password='password123', phone_number='+254700000973')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _book(self, stage):
        return self.client.post(
            reverse('bookings:create-booking'),
            {'trip_id': self.trip.id, 'seats': 1, 'pickup_stage_id': stage.id},
            format='json')

    def test_last_stage_cannot_be_booked_as_pickup(self):
        resp = self._book(self.last)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('where this trip ends', resp.data['error'])

    def test_a_stage_along_the_way_can_be_booked(self):
        self.assertEqual(self._book(self.mid).status_code, 201)


class OpenBookingsFollowTheNewStagesTests(TestCase):
    def test_a_rider_booked_at_a_replaced_stage_moves_to_the_nearest_new_one(self):
        import importlib

        from django.apps import apps

        company = Company.objects.get(name='CityShuttle')
        route = Route.objects.get(company=company, name='CBD to Ngong Road')
        old = PickupStage.objects.create(
            route=route, name='Kencom House', order=1,
            latitude=-1.285582, longitude=36.824962)
        driver = Driver.objects.create(
            name='Net Driver 2', phone_number='+254700000974',
            bus_number='KDN 002A', company=company)
        trip = Trip.objects.create(
            route=route, driver=driver, capacity=14, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=2))
        user = get_user_model().objects.create_user(
            username='pax_move', password='password123', phone_number='+254700000975')
        booking = Booking.objects.create(
            user=user, route=route, trip=trip, pickup_stage=old,
            pickup_location=old.name, seats=1, total_amount=70, status='confirmed')

        migration = importlib.import_module(
            'companies.migrations.0019_real_stages_and_return_routes')
        migration.install(apps, None)

        booking.refresh_from_db()
        self.assertTrue(booking.pickup_stage.is_active)
        self.assertEqual(booking.pickup_stage.name, 'Kencom')
        self.assertEqual(booking.pickup_location, 'Kencom')



class LongDistanceUpgradeTests(TestCase):
    """0020 on a database that ran 0019 before the town stages existed."""

    def test_open_booking_on_a_dropped_stage_moves_to_a_new_one(self):
        import importlib

        from django.apps import apps
        migration = importlib.import_module('companies.migrations.0020_long_distance_town_stages')
        route = Route.objects.get(company__name='Supermetro', name='Nairobi to Kisumu')
        old = PickupStage.objects.create(
            route=route, name='Old Narok Stop', order=2, latitude=-1.08, longitude=35.87)
        driver = Driver.objects.create(
            name='LD Driver', phone_number='+254700000981', bus_number='KDL 001A',
            company=route.company)
        trip = Trip.objects.create(
            route=route, driver=driver, capacity=14, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=2))
        rider = get_user_model().objects.create_user(
            username='ld_rider', password='password123', phone_number='+254700000982')
        booking = Booking.objects.create(
            user=rider, route=route, trip=trip, pickup_stage=old,
            pickup_location=old.name, seats=1, total_amount=1000, status='confirmed')

        migration.install(apps, None)

        old.refresh_from_db()
        booking.refresh_from_db()
        active = list(route.pickup_stages.filter(is_active=True).order_by('order'))
        self.assertFalse(old.is_active)
        self.assertEqual([s.name for s in active][1:-1],
                         ['Naivasha', 'Gilgil', 'Nakuru', 'Kericho', 'Awasi', 'Ahero'])
        self.assertIn(booking.pickup_stage, active[:-1])
        self.assertEqual(booking.pickup_location, booking.pickup_stage.name)
