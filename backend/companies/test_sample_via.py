from django.test import SimpleTestCase

from companies.routing import sample_via

LINE6 = {'type': 'LineString', 'coordinates': [
    [36.80, -1.30], [36.80, -1.28], [36.80, -1.26],
    [36.80, -1.24], [36.80, -1.22], [36.80, -1.20]]}


class SampleViaTests(SimpleTestCase):

    def test_spreads_points_along_the_line_as_lat_lng(self):
        self.assertEqual(
            sample_via(LINE6, 3),
            [(-1.26, 36.8), (-1.24, 36.8), (-1.22, 36.8)])

    def test_points_follow_the_direction_of_the_line(self):
        reversed_line = {'type': 'LineString', 'coordinates': LINE6['coordinates'][::-1]}
        lats = [p[0] for p in sample_via(reversed_line, 3)]
        self.assertEqual(len(lats), 3)
        self.assertEqual(lats, sorted(lats, reverse=True))

    def test_never_returns_endpoints_or_duplicates(self):
        self.assertEqual(
            sample_via(LINE6, 20),
            [(-1.28, 36.8), (-1.26, 36.8), (-1.24, 36.8), (-1.22, 36.8)])

    def test_line_with_fewer_than_three_coordinates_gives_nothing(self):
        two = {'type': 'LineString', 'coordinates': [[36.80, -1.30], [36.80, -1.20]]}
        self.assertEqual(sample_via(two, 5), [])

    def test_count_below_one_gives_nothing(self):
        self.assertEqual(sample_via(LINE6, 0), [])

    def test_zero_length_line_gives_nothing(self):
        same = {'type': 'LineString', 'coordinates': [[36.80, -1.30]] * 3}
        self.assertEqual(sample_via(same, 3), [])
