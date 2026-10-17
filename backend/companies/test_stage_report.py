from unittest.mock import patch

from django.test import SimpleTestCase

from companies.routing import RoutingError, plan_line

START = (-1.30, 36.80)
END = (-1.30, 36.90)
FAR = (-1.28, 36.85)


def linear(points):
    coords = [[lng, lat] for lat, lng in points]
    return {'type': 'LineString', 'coordinates': coords}, 11000.0


class StageReportTests(SimpleTestCase):
    def test_a_road_service_failure_is_reported_not_hidden(self):
        def fake(points):
            if len(points) == 2:
                return linear(points)
            raise RoutingError('busy')

        report = []
        with patch('companies.routing.road_line', side_effect=fake):
            _g, _d, followed, skipped = plan_line(
                START, END, [], [(7, 'Far', *FAR)], report=report)
        self.assertEqual((followed, skipped), ([], [7]))
        self.assertEqual(report[0]['stage_id'], 7)
        self.assertIn('road service failed', report[0]['outcome'])

    def test_a_busy_road_service_is_retried(self):
        calls = {'n': 0}

        def flaky(points):
            calls['n'] += 1
            if calls['n'] == 1:
                raise RoutingError('busy')
            return linear(points)

        with patch('companies.routing.road_line', side_effect=flaky), patch('time.sleep'):
            geometry, _d, _f, _s = plan_line(START, END, [], [], retries=2)
        self.assertEqual(calls['n'], 2)
        self.assertEqual(len(geometry['coordinates']), 2)

    def test_a_pull_that_adds_spurs_says_so(self):
        stub = {'type': 'LineString', 'coordinates': [
            [36.80, -1.30], [36.85, -1.30], [36.85, -1.2973],
            [36.85, -1.30], [36.90, -1.30]]}

        def fake(points):
            return linear(points) if len(points) == 2 else (stub, 1.0)

        report = []
        with patch('companies.routing.road_line', side_effect=fake):
            plan_line(START, END, [], [(8, 'Side', -1.2973, 36.85)], report=report)
        self.assertEqual(len(report), 1)
        self.assertIn('spur', report[0]['outcome'])
