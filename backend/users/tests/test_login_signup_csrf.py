"""login and signup are AllowAny, so they must check the CSRF token and the Origin themselves."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

User = get_user_model()
LOC = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
GOOD_ORIGIN = 'http://localhost:5173'
EVIL_ORIGIN = 'https://evil.example'
LOGIN = {'phone_number': '0711900001', 'password': 'pw-123456'}
SIGNUP = {'phone_number': '0711900002', 'password': 'Zx9-longer-pass', 'name': 'Alice Wanjiru'}


@override_settings(CACHES=LOC)
class LoginSignupCsrfTests(TestCase):
    def setUp(self):
        User.objects.create_user(username='paxb', password='pw-123456', phone_number='+254711900001')

    def post(self, url, body, client=None, token=None, origin=None):
        extra = {}
        if token:
            extra['HTTP_X_CSRFTOKEN'] = token
        if origin:
            extra['HTTP_ORIGIN'] = origin
        return (client or Client(enforce_csrf_checks=True)).post(
            url, body, content_type='application/json', **extra)

    def bootstrap(self):
        client = Client(enforce_csrf_checks=True)
        token = client.get('/api/users/csrf/').json()['csrfToken']
        return client, token

    def test_the_csrf_endpoint_sets_the_cookie_and_returns_the_token(self):
        client, token = self.bootstrap()
        self.assertTrue(token)
        self.assertIn('csrftoken', client.cookies)

    def test_login_without_a_token_is_403_and_does_not_sign_in(self):
        r = self.post('/api/users/login/', LOGIN, origin=EVIL_ORIGIN)
        self.assertEqual(r.status_code, 403, r.content[:120])
        r = self.post('/api/users/login/', LOGIN)
        self.assertEqual(r.status_code, 403, r.content[:120])
        self.assertNotIn('sessionid', r.cookies)

    def test_login_with_a_valid_token_and_the_frontend_origin_works(self):
        client, token = self.bootstrap()
        r = self.post('/api/users/login/', LOGIN, client, token, GOOD_ORIGIN)
        self.assertEqual(r.status_code, 200, r.content[:120])

    def test_login_with_a_valid_token_from_a_foreign_origin_is_403(self):
        client, token = self.bootstrap()
        r = self.post('/api/users/login/', LOGIN, client, token, EVIL_ORIGIN)
        self.assertEqual(r.status_code, 403, r.content[:120])

    def test_login_with_a_wrong_token_is_403(self):
        client, token = self.bootstrap()
        r = self.post('/api/users/login/', LOGIN, client, 'x' * len(token), GOOD_ORIGIN)
        self.assertEqual(r.status_code, 403, r.content[:120])

    def test_signup_without_a_token_is_403_and_creates_nothing(self):
        before = User.objects.count()
        for path in ('/api/users/signup/', '/api/users/register/'):
            r = self.post(path, SIGNUP, origin=EVIL_ORIGIN)
            self.assertEqual(r.status_code, 403, r.content[:120])
        self.assertEqual(User.objects.count(), before)

    def test_signup_with_a_valid_token_and_the_frontend_origin_works(self):
        client, token = self.bootstrap()
        r = self.post('/api/users/signup/', SIGNUP, client, token, GOOD_ORIGIN)
        self.assertEqual(r.status_code, 201, r.content[:160])

    def test_signup_with_a_valid_token_from_a_foreign_origin_is_403(self):
        client, token = self.bootstrap()
        r = self.post('/api/users/signup/', SIGNUP, client, token, EVIL_ORIGIN)
        self.assertEqual(r.status_code, 403, r.content[:120])
