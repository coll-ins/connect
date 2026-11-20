from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

SECRET = 'test-secret-' + 'x' * 30
URL = '/api/internal/cron/close-stale-trips/'
LOCK = 'cron-lock:close-stale-trips'


@override_settings(CRON_SECRET=SECRET)
class CronEndpointTests(TestCase):
    def setUp(self):
        cache.clear()

    def post(self, secret=SECRET, url=URL):
        headers = {'HTTP_X_CRON_SECRET': secret} if secret is not None else {}
        return self.client.post(url, **headers)

    def test_wrong_or_missing_secret_is_404_and_runs_nothing(self):
        with mock.patch('connect.cron.call_command') as cc:
            self.assertEqual(self.post('nope').status_code, 404)
            self.assertEqual(self.post(None).status_code, 404)
            cc.assert_not_called()

    @override_settings(CRON_SECRET='')
    def test_unset_secret_disables_the_endpoint(self):
        with mock.patch('connect.cron.call_command') as cc:
            self.assertEqual(self.post('').status_code, 404)
            cc.assert_not_called()

    def test_get_and_unknown_job_are_404(self):
        with mock.patch('connect.cron.call_command') as cc:
            r = self.client.get(URL, HTTP_X_CRON_SECRET=SECRET)
            self.assertEqual(r.status_code, 404)
            self.assertEqual(self.post(url='/api/internal/cron/nope/').status_code, 404)
            cc.assert_not_called()

    def test_good_secret_runs_the_job_and_releases_the_lock(self):
        with mock.patch('connect.cron.call_command') as cc:
            r = self.post()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(cc.call_args[0][0], 'close_stale_trips')
        self.assertIsNone(cache.get(LOCK))

    def test_overlapping_run_is_refused(self):
        cache.set(LOCK, '1', 60)
        with mock.patch('connect.cron.call_command') as cc:
            r = self.post()
        self.assertEqual(r.status_code, 202)
        cc.assert_not_called()

    def test_failure_is_500_and_releases_the_lock(self):
        with mock.patch('connect.cron.call_command', side_effect=RuntimeError('boom')):
            r = self.post()
        self.assertEqual(r.status_code, 500)
        self.assertIsNone(cache.get(LOCK))


class CronJobRegistryTests(TestCase):
    def test_wallet_sweeps_job_runs_the_wallet_sweeps_command(self):
        from connect.cron import JOBS
        self.assertEqual(JOBS['wallet-sweeps'], ('wallet_sweeps', []))

    def test_every_job_is_a_real_command_and_is_scheduled(self):
        from pathlib import Path
        from django.core.management import get_commands
        from django.conf import settings
        from connect.cron import JOBS
        commands = get_commands()
        for job, (name, _args) in JOBS.items():
            self.assertIn(name, commands, f'{job} points at a missing command')
        workflow = Path(settings.BASE_DIR).parent / '.github' / 'workflows' / 'scheduled-jobs.yml'
        text = workflow.read_text(encoding='utf-8')
        for job in JOBS:
            self.assertIn(job, text, f'{job} is never called by scheduled-jobs.yml')
