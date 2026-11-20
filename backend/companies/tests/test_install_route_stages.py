from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from companies.management.commands import install_route_stages as cmd
from companies.models import PickupStage, Route


def run(*args):
    out = StringIO()
    call_command('install_route_stages', *args, stdout=out)
    return out.getvalue()


class StageKeysMatchSeededRoutesTests(TestCase):
    def test_install_route_stages_names_match_seeded_routes(self):
        seeded = set(Route.objects.values_list('name', flat=True))
        self.assertGreaterEqual(Route.objects.count(), 35)
        unmatched = []
        for key in cmd.STAGES:
            names = {key, *cmd.ROUTE_ALIASES.get(key, [])}
            if not names & seeded:
                unmatched.append(key)
        # "Kamau" is a hand-made route from an old database; nothing seeds it.
        self.assertEqual(unmatched, ['Kamau'])
        for key in ('Nairobi to Kisumu', 'Nairobi to Kakamega', 'Nairobi to Nakuru'):
            self.assertTrue(Route.objects.filter(name=key).exists())

    def test_aliased_routes_get_their_stages_in_order(self):
        with mock.patch.object(cmd.Command, 'geocode', return_value=(1, 2)):
            run()
        for route_name, key in (('Nairobi to Kisumu', 'CBD to Kisumu'),
                                ('Nairobi to Kakamega', 'CBD to Kakamega'),
                                ('Nairobi to Nakuru', 'CBD to Nakuru')):
            route = Route.objects.get(name=route_name)
            self.assertEqual(
                list(route.pickup_stages.order_by('order').values_list('name', flat=True)),
                cmd.STAGES[key])

    def test_rerun_creates_nothing_new(self):
        with mock.patch.object(cmd.Command, 'geocode', return_value=(1, 2)):
            run()
            before = PickupStage.objects.count()
            run()
        self.assertEqual(PickupStage.objects.count(), before)


class OfflineModeTests(TestCase):
    def test_offline_never_touches_the_network_and_uses_committed_coordinates(self):
        with mock.patch('companies.management.commands.install_route_stages.requests.get',
                        side_effect=AssertionError('network used')) as get:
            output = run('--offline')
        get.assert_not_called()
        route = Route.objects.filter(name='CBD to Ngong').first()
        names = list(route.pickup_stages.order_by('order').values_list('name', flat=True))
        self.assertEqual(names, ['Kencom House', 'Nyayo Stadium', 'Karen / Dagoretti Corner',
                                 'Kiserian Junction', 'Ngong Town'])
        stage = route.pickup_stages.get(name='Kencom House')
        self.assertEqual((str(stage.latitude), str(stage.longitude)), ('-1.285582', '36.824962'))
        self.assertIn('no offline coordinate: Kisumu', output)
        self.assertFalse(Route.objects.get(name='Nairobi to Kisumu').pickup_stages.exists())
