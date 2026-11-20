"""The Django admin login has the same lockout as the API login, and is off unless enabled."""
import importlib
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import clear_url_caches

from users.throttles import LOGIN_FAILURES_PER_CLIENT

User = get_user_model()
LOC = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
PASSWORD = 'Correct-horse-9'


def remount(enabled):
    from connect import urls
    with override_settings(ADMIN_SITE_ENABLED=enabled):
        importlib.reload(urls)
        clear_url_caches()


@override_settings(CACHES=LOC, STORAGES=STORAGES)
class AdminLoginLockoutTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        remount(True)
        self.addCleanup(remount, True)
        self.admin = User.objects.create_user(
            username='boss', password=PASSWORD, phone_number='+254711000000',
            is_superuser=True, is_staff=True)

    def login(self, password, client=None, username='boss'):
        return (client or Client()).post(
            '/admin/login/', {'username': username, 'password': password, 'next': '/admin/'})

    def test_the_correct_password_signs_in(self):
        self.assertEqual(self.login(PASSWORD).status_code, 302)

    def test_ten_wrong_guesses_lock_out_even_the_correct_password(self):
        client = Client()
        for _ in range(LOGIN_FAILURES_PER_CLIENT):
            self.assertEqual(self.login('wrong-guess', client).status_code, 200)
        self.assertEqual(self.login(PASSWORD, client).status_code, 429)
        self.assertEqual(self.login(PASSWORD).status_code, 429)

    def test_a_success_does_not_reset_the_count(self):
        for _ in range(LOGIN_FAILURES_PER_CLIENT - 1):
            self.login('wrong-guess')
        self.assertEqual(self.login(PASSWORD).status_code, 302)
        self.assertEqual(self.login('wrong-guess').status_code, 200)
        self.assertEqual(self.login(PASSWORD).status_code, 429)

    def test_the_admin_login_page_is_still_shown_on_get(self):
        self.assertEqual(Client().get('/admin/login/').status_code, 200)

    def test_the_lockout_is_shared_with_the_api_login(self):
        client = Client()
        for _ in range(LOGIN_FAILURES_PER_CLIENT):
            self.assertEqual(client.post('/api/users/login/', {
                'phone_number': '0711000000', 'password': 'wrong-guess'},
                content_type='application/json').status_code, 401)
        self.assertEqual(self.login(PASSWORD, client).status_code, 429)


@override_settings(CACHES=LOC, STORAGES=STORAGES)
class AdminSiteSwitchTests(TestCase):
    def tearDown(self):
        remount(True)

    def test_the_admin_is_not_mounted_when_it_is_switched_off(self):
        remount(False)
        self.assertEqual(Client().get('/admin/login/').status_code, 404)
        self.assertEqual(Client().get('/admin/').status_code, 404)
        self.assertEqual(Client().post('/admin/login/', {'username': 'x', 'password': 'y'}).status_code, 404)

    def test_the_admin_is_mounted_when_it_is_switched_on(self):
        remount(True)
        self.assertEqual(Client().get('/admin/login/').status_code, 200)


class EnsureSuperuserPasswordRulesTests(TestCase):
    def run_it(self, password):
        out, err = StringIO(), StringIO()
        env = {'ADMIN_PHONE': '0712345678', 'ADMIN_PASSWORD': password}
        with mock.patch.dict('os.environ', env):
            call_command('ensure_superuser', stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_a_weak_admin_password_creates_no_account_and_is_never_printed(self):
        for weak in ('12345678', 'iloveyou', 'short1'):
            out, err = self.run_it(weak)
            self.assertEqual(User.objects.filter(is_superuser=True).count(), 0, weak)
            self.assertIn('does not pass the password rules', err)
            self.assertNotIn(weak, out + err)

    def test_a_strong_admin_password_still_creates_the_account(self):
        out, err = self.run_it('Str0ng-admin-pass')
        self.assertEqual(out.strip(), 'superuser ensured')
        self.assertEqual(User.objects.filter(is_superuser=True).count(), 1)
