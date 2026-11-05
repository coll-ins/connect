from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from companies.models import Company, DemoTripSimulation, Route, Trip
from drivers.models import Driver

User = get_user_model()
COLLECTION_URL = '/api/system/demo-simulation/'


@override_settings(DEMO_SIMULATION_ENABLED=True)
class DemoSimulationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(
            name='Demo Transit',
            areas_served='Nairobi',
        )
        self.route = Route.objects.create(
            company=self.company,
            name='CBD to Westlands',
            start_point='CBD',
            end_point='Westlands',
            price='100.00',
            geometry={
                'type': 'LineString',
                'coordinates': [
                    [36.8219, -1.2864],
                    [36.8230, -1.2870],
                    [36.8250, -1.2890],
                ],
            },
        )
        self.admin = User.objects.create_superuser(
            username='demo_platform_admin',
            password='test-only-password',
            phone_number='+254700000111',
            email='demo-admin@example.test',
        )
        self.manager = User.objects.create_user(
            username='demo_company_manager',
            password='test-only-password',
            phone_number='+254700000112',
            role='company_manager',
            company=self.company,
        )

    def authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.admin)

    def start_simulation(self, route_id=None):
        self.authenticate()
        return self.client.post(
            COLLECTION_URL,
            {'route_id': route_id or self.route.id},
            format='json',
        )

    def test_only_superusers_can_read_start_advance_or_stop(self):
        self.authenticate(self.manager)
        self.assertEqual(
            self.client.get(COLLECTION_URL).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(
                COLLECTION_URL,
                {'route_id': self.route.id},
                format='json',
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        anonymous_client = APIClient()
        self.assertEqual(
            anonymous_client.get(COLLECTION_URL).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_disabled_feature_is_not_available_even_to_superusers(self):
        self.authenticate()
        with override_settings(DEMO_SIMULATION_ENABLED=False):
            response = self.client.post(
                COLLECTION_URL,
                {'route_id': self.route.id},
                format='json',
            )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(DemoTripSimulation.objects.count(), 0)

    def test_start_is_idempotent_and_isolated_from_live_trip_data(self):
        first = self.start_simulation()
        second = self.start_simulation()

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data['simulation']['id'], second.data['simulation']['id'])
        self.assertEqual(DemoTripSimulation.objects.filter(status='running').count(), 1)
        self.assertEqual(Trip.objects.count(), 0)
        self.assertEqual(Driver.objects.count(), 0)
        self.assertEqual(first.data['simulation']['path'][0], [-1.2864, 36.8219])
        self.assertEqual(first.data['simulation']['progress'], 0)

    def test_available_routes_excludes_routes_without_valid_map_path(self):
        route_without_map = Route.objects.create(
            company=self.company,
            name='No map points',
            start_point='A',
            end_point='B',
            price='100.00',
        )
        self.authenticate()

        response = self.client.get(COLLECTION_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [route['id'] for route in response.data['available_routes']],
            [self.route.id],
        )
        self.assertNotEqual(self.route.id, route_without_map.id)

    def test_repeated_progress_calls_finish_then_reject_further_changes(self):
        start = self.start_simulation()
        simulation_id = start.data['simulation']['id']
        progress = start.data['simulation']['progress']
        final = None

        while progress < 100:
            response = self.client.post(
                f'{COLLECTION_URL}{simulation_id}/advance/',
                {},
                format='json',
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            final = response.data['simulation']
            progress = final['progress']

        self.assertEqual(final['status'], 'completed')
        self.assertEqual(
            self.client.post(
                f'{COLLECTION_URL}{simulation_id}/advance/',
                {},
                format='json',
            ).status_code,
            status.HTTP_409_CONFLICT,
        )
        self.assertEqual(Trip.objects.count(), 0)

    def test_stop_halts_progress_and_replay_is_rejected(self):
        simulation_id = self.start_simulation().data['simulation']['id']

        stopped = self.client.post(
            f'{COLLECTION_URL}{simulation_id}/stop/',
            {},
            format='json',
        )

        self.assertEqual(stopped.status_code, status.HTTP_200_OK)
        self.assertEqual(stopped.data['simulation']['status'], 'stopped')
        self.client.force_authenticate(self.manager)
        self.assertEqual(
            self.client.post(
                f'{COLLECTION_URL}{simulation_id}/stop/',
                {},
                format='json',
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.client.force_authenticate(self.admin)
        self.assertEqual(
            self.client.post(
                f'{COLLECTION_URL}{simulation_id}/advance/',
                {},
                format='json',
            ).status_code,
            status.HTTP_409_CONFLICT,
        )

    def test_start_rejects_bad_route_ids_and_routes_without_map_points(self):
        self.authenticate()
        for route_id in ('not-an-id', True, 999999):
            response = self.client.post(
                COLLECTION_URL,
                {'route_id': route_id},
                format='json',
            )
            expected = (
                status.HTTP_400_BAD_REQUEST
                if route_id in ('not-an-id', True)
                else status.HTTP_404_NOT_FOUND
            )
            self.assertEqual(response.status_code, expected)

        route_without_map = Route.objects.create(
            company=self.company,
            name='No map points',
            start_point='A',
            end_point='B',
            price='100.00',
        )
        response = self.client.post(
            COLLECTION_URL,
            {'route_id': route_without_map.id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(DemoTripSimulation.objects.count(), 0)

    def test_expired_running_session_is_not_returned_as_active(self):
        simulation_id = self.start_simulation().data['simulation']['id']
        DemoTripSimulation.objects.filter(pk=simulation_id).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        response = self.client.get(COLLECTION_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['simulation']['status'], 'expired')
        self.assertEqual(
            DemoTripSimulation.objects.get(pk=simulation_id).status,
            'expired',
        )
