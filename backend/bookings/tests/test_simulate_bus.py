import json

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from companies.models import Company, Route, Trip
from companies.geo import haversine_m, orient_path, parse_geometry, point_along
from companies.management.commands.simulate_bus import path_length_m
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
    def test_trip_option_is_required(self):
        with self.assertRaises(CommandError):
            call_command('simulate_bus')

    @override_settings(DEBUG=True, APP_ENVIRONMENT='production')
    def test_command_is_disabled_in_production_even_if_debug_is_enabled(self):
        with self.assertRaisesMessage(
            CommandError,
            'simulate_bus is limited to non-production DEBUG environments.',
        ):
            call_command('simulate_bus', trip=1)
