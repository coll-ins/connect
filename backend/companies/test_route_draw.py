import json
from unittest.mock import patch

from django.test import SimpleTestCase

from companies.routing import RoutingError, road_alternatives, sample_via


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self.payload).encode('utf-8')


def line(*coords):
    return {'type': 'LineString', 'coordinates': [list(c) for c in coords]}


class SampleViaTests(SimpleTestCase):
    def test_points_are_spread_in_travel_order_and_skip_the_ends(self):
        coords = [(36.80 + i * 0.01, -1.30) for i in range(11)]
        points = sample_via(line(*coords), 2)
        self.assertEqual(len(points), 2)
        self.assertLess(points[0][1], points[1][1])
        for lat, lng in points:
            self.assertNotIn((lat, lng), [(-1.3, 36.8), (-1.3, 36.9)])

    def test_a_line_with_no_middle_gives_no_points(self):
        self.assertEqual(sample_via(line((36.8, -1.3), (36.9, -1.3)), 2), [])


class RoadAlternativesTests(SimpleTestCase):
    def test_every_usable_road_is_returned_and_unusable_ones_dropped(self):
        payload = {'code': 'Ok', 'routes': [
            {'geometry': line((36.8, -1.3), (36.9, -1.3)), 'distance': 11000},
            {'geometry': {'type': 'Point', 'coordinates': [0, 0]}, 'distance': 5},
            {'geometry': line((36.8, -1.3), (36.85, -1.28), (36.9, -1.3)), 'distance': 12000},
        ]}
        with patch('urllib.request.urlopen', return_value=FakeResponse(payload)) as mocked:
            found = road_alternatives([(-1.3, 36.8), (-1.3, 36.9)], count=3)
        self.assertEqual([d for _g, d in found], [11000.0, 12000.0])
        self.assertIn('alternatives=3', mocked.call_args[0][0].full_url)

    def test_no_road_found_is_reported(self):
        with patch('urllib.request.urlopen',
                   return_value=FakeResponse({'code': 'NoRoute', 'routes': []})):
            with self.assertRaises(RoutingError):
                road_alternatives([(-1.3, 36.8), (-1.3, 36.9)])

    def test_a_down_road_service_is_reported(self):
        with patch('urllib.request.urlopen', side_effect=OSError('down')):
            with self.assertRaises(RoutingError):
                road_alternatives([(-1.3, 36.8), (-1.3, 36.9)])
