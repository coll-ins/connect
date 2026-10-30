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
