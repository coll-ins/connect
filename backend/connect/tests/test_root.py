from django.test import SimpleTestCase


class RootHealthCheckTests(SimpleTestCase):
    def test_root_returns_api_health_instead_of_missing_frontend_template(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {'status': 'ok', 'service': 'CONNECT API'},
        )
