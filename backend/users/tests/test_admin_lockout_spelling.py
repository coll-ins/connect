"""The admin lockout counts the name the way the admin form reads it, and a success never frees the API login."""
from django.test import Client, TestCase, override_settings

from users.tests.test_admin_site_lockout import (
    LOC, STORAGES, PASSWORD, remount, User)
from users.throttles import LOGIN_FAILURES_PER_CLIENT, login_blocked, record_login_failure

PHONE = '+254711000000'


@override_settings(CACHES=LOC, STORAGES=STORAGES)
class AdminLockoutSpellingTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        remount(True)
        self.addCleanup(remount, True)
        User.objects.create_user(
            username='collins', password=PASSWORD, phone_number=PHONE,
            is_superuser=True, is_staff=True)

    def post(self, username, password, client=None, ip=None):
        extra = {'REMOTE_ADDR': ip} if ip else {}
        return (client or Client()).post(
            '/admin/login/', {'username': username, 'password': password, 'next': '/admin/'}, **extra)

    def guess_then_try_right(self, spelling, right='collins'):
        c = Client()
        for _ in range(LOGIN_FAILURES_PER_CLIENT):
            self.post(spelling, 'wrong-guess', c)
        return self.post(right, PASSWORD, c).status_code

    def test_padded_username_guesses_still_lock_out(self):
        self.assertEqual(self.guess_then_try_right('collins '), 429)

    def test_leading_and_trailing_whitespace_both_count(self):
        self.assertEqual(self.guess_then_try_right('\t collins\n'), 429)

    def test_a_compatibility_spelling_counts_as_the_same_name(self):
        # Full-width letters fold to ASCII under NFKC, as in the admin form.
        self.assertEqual(self.guess_then_try_right('ｃｏｌｌｉｎｓ'), 429)

    def test_mixed_spellings_share_one_count(self):
        c = Client()
        spellings = ['collins', 'collins ', ' collins', 'ｃｏｌｌｉｎｓ']
        for i in range(LOGIN_FAILURES_PER_CLIENT):
            self.post(spellings[i % 4], 'wrong-guess', c)
        self.assertEqual(self.post('collins', PASSWORD, c).status_code, 429)

    def test_unknown_names_are_counted_by_client_ip(self):
        c = Client()
        for i in range(LOGIN_FAILURES_PER_CLIENT):
            self.assertEqual(self.post(f'nobody-{i}', 'x', c, ip='10.9.8.7').status_code, 200)
        self.assertEqual(self.post('nobody-next', 'x', c, ip='10.9.8.7').status_code, 429)
        self.assertEqual(self.post('nobody-next', 'x', c, ip='10.9.8.8').status_code, 200)

    def test_the_right_password_stays_locked_after_the_limit(self):
        self.assertEqual(self.guess_then_try_right('collins'), 429)

    def test_an_admin_success_does_not_reset_the_api_login_lockout(self):
        for _ in range(LOGIN_FAILURES_PER_CLIENT - 1):
            record_login_failure(PHONE, '127.0.0.1')
        self.assertEqual(self.post('collins', PASSWORD).status_code, 302)
        record_login_failure(PHONE, '127.0.0.1')
        self.assertTrue(login_blocked(PHONE, '127.0.0.1'))
