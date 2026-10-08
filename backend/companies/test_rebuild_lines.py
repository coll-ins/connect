import io
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from rest_framework.test import APITestCase

from bookings.tests.test_round5 import _Fixture
from companies.models import PickupStage, Route
from companies.test_route_health import STRAIGHT, STUB


class RebuildRouteLinesTests(_Fixture, APITestCase):
    def setUp(self):
        self.build('2801')
        self.route = self.trip.route
        Route.objects.filter(pk=self.route.pk).update(
            start_latitude=Decimal('-1.300000'), start_longitude=Decimal('36.800000'),
            end_latitude=Decimal('-1.300000'), end_longitude=Decimal('36.820000'),
            geometry=STUB)

    def _run(self, **kwargs):
        out = io.StringIO()
        with patch('companies.routing.road_line', return_value=(STRAIGHT, 12000.0)):
            call_command('rebuild_route_lines', route=[self.route.id], pause=0,
                         stdout=out, **kwargs)
        self.route.refresh_from_db()
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        output = self._run()
        self.assertIn('would apply', output)
        self.assertEqual(self.route.geometry, STUB)

    def test_apply_replaces_the_line(self):
        output = self._run(apply=True)
        self.assertIn('applied', output)
        self.assertEqual(self.route.geometry, STRAIGHT)

    def test_route_without_coordinates_is_skipped(self):
        Route.objects.filter(pk=self.route.pk).update(start_latitude=None)
        output = self._run(apply=True)
        self.assertIn('no start/end coordinates', output)
        self.assertEqual(self.route.geometry, STUB)

    def test_a_stage_that_would_be_off_the_line_blocks_the_save(self):
        PickupStage.objects.create(
            route=self.route, name='R28 Far Stage',
            latitude=Decimal('-1.290000'), longitude=Decimal('36.810000'), order=1)
        output = self._run(apply=True)
        self.assertIn('NEEDS YOU', output)
        self.assertEqual(self.route.geometry, STUB)
