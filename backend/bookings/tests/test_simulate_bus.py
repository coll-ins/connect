import json

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from companies.models import Company, Route, Trip
from companies.management.commands.simulate_bus import (
    haversine_m, orient_path, parse_geometry, path_length_m, point_along,
)
from drivers.models import Driver

LINE = {'type': 'LineString', 'coordinates': [[36.82, -1.28], [36.83, -1.29]]}


class SimulatorMathTests(SimpleTestCase):
    def test_geojson_is_read_as_lng_lat(self):
        self.assertEqual(parse_geometry(LINE), [(-1.28, 36.82), (-1.29, 36.83)])

    def test_feature_string_and_multiline_forms(self):
        feat = {'type': 'Feature', 'geometry': LINE}
        self.assertEqual(len(parse_geometry(feat)), 2)
        self.assertEqual(len(parse_geometry(json.dumps(feat))), 2)
        multi = {'type': 'MultiLineString', 'coordinates': [LINE['coordinates'], LINE['coordinates']]}
        self.assertEqual(len(parse_geometry(multi)), 4)

    def test_junk_geometry_is_rejected(self):
        for bad in (None, '', 'not json', {}, [], {'type': 'Point', 'coordinates': [1, 2]},
                    {'type': 'LineString', 'coordinates': [[1, 2]]}):
            self.assertIsNone(parse_geometry(bad), bad)

    def test_path_is_oriented_to_start_at_the_stage(self):
        path = [(-1.30, 36.80), (-1.29, 36.81), (-1.28, 36.82)]
        self.assertEqual(orient_path(path, (-1.2801, 36.8201))[0], (-1.28, 36.82))
        self.assertEqual(orient_path(path, (-1.30, 36.80))[0], (-1.30, 36.80))

    def test_point_along_walks_and_finishes(self):
        a, b = (-1.28, 36.82), (-1.28, 36.83)
        total = haversine_m(a, b)
        self.assertAlmostEqual(path_length_m([a, b]), total, places=3)
        (lat, lng), done = point_along([a, b], total / 2)
        self.assertFalse(done)
        self.assertAlmostEqual(lng, 36.825, places=4)
        self.assertTrue(point_along([a, b], total + 10)[1])


@override_settings(DEBUG=True, APP_ENVIRONMENT='development')
class SimulatorCommandSafetyTests(TestCase):
    def test_explicit_trip_option_rejects_non_demo_bus(self):
        company = Company.objects.create(
            name='Simulator Safety Co',
            areas_served='Nairobi',
        )
        route = Route.objects.create(
            company=company,
            name='Route A',
            start_point='A',
            end_point='B',
            price='100.00',
        )
        driver = Driver.objects.create(
            name='Real Driver',
            phone_number='+254700000091',
            bus_number='KAA 001A',
            company=company,
        )
        trip = Trip.objects.create(
            route=route,
            driver=driver,
            departure_at=timezone.now(),
            capacity=30,
        )

        with self.assertRaisesMessage(
            CommandError,
            'simulate_bus only moves trips assigned to a DEMO-prefixed bus.',
        ):
            call_command('simulate_bus', trip=trip.id)

        trip.refresh_from_db()
        driver.refresh_from_db()
        self.assertEqual(trip.status, 'scheduled')
        self.assertIsNone(driver.latitude)
        self.assertIsNone(driver.longitude)

    @override_settings(DEBUG=True, APP_ENVIRONMENT='production')
    def test_command_is_disabled_in_production_even_if_debug_is_enabled(self):
        with self.assertRaisesMessage(
            CommandError,
            'simulate_bus is limited to non-production DEBUG environments.',
        ):
            call_command('simulate_bus', trip=1)
