from django.core.cache import cache
from rest_framework.test import APITestCase

from users.models import CustomUser


class LoginLockout(APITestCase):
    """An anonymous attacker who knows only a victim's phone must not be able to lock the victim out."""

    def setUp(self):
        cache.clear()
        CustomUser.objects.create_user(
            username='victim', phone_number='+254712345678', password='Str0ng-pass-91')

    def test_attacker_cannot_lock_out_victim(self):
        for i in range(12):
            # different spoofed clients; per-phone bucket is shared
            self.client.post('/api/users/login/', {'phone_number': '0712345678', 'password': f'bad{i}'},
                             format='json', REMOTE_ADDR=f'10.0.0.{i + 1}')
        r = self.client.post('/api/users/login/', {'phone_number': '0712345678', 'password': 'Str0ng-pass-91'},
                             format='json', REMOTE_ADDR='10.9.9.9')
        self.assertEqual(r.status_code, 200, f'victim locked out with correct password: {r.status_code}')

    def test_one_client_guessing_is_blocked_then_cleared_by_success(self):
        for i in range(10):
            self.client.post('/api/users/login/', {'phone_number': '0712345678', 'password': f'bad{i}'},
                             format='json', REMOTE_ADDR='10.1.1.1')
        r = self.client.post('/api/users/login/', {'phone_number': '0712345678', 'password': 'Str0ng-pass-91'},
                             format='json', REMOTE_ADDR='10.1.1.1')
        self.assertEqual(r.status_code, 429)
        # The owner on another connection still gets in, and that clears the lockout everywhere.
        r = self.client.post('/api/users/login/', {'phone_number': '0712345678', 'password': 'Str0ng-pass-91'},
                             format='json', REMOTE_ADDR='10.2.2.2')
        self.assertEqual(r.status_code, 200)
        self.client.logout()
        r = self.client.post('/api/users/login/', {'phone_number': '0712345678', 'password': 'Str0ng-pass-91'},
                             format='json', REMOTE_ADDR='10.1.1.1')
        self.assertEqual(r.status_code, 200)

    def test_unknown_phone_counts_as_failure(self):
        for i in range(10):
            self.client.post('/api/users/login/', {'phone_number': '0799999999', 'password': 'x'},
                             format='json', REMOTE_ADDR='10.3.3.3')
        r = self.client.post('/api/users/login/', {'phone_number': '0799999999', 'password': 'x'},
                             format='json', REMOTE_ADDR='10.3.3.3')
        self.assertEqual(r.status_code, 429)
