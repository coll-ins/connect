"""Route price must be positive; garbage ids in company endpoints are 400s."""
from django.test import TestCase

from bookings.tests.review_base import WorldMixin

FUTURE = '2030-01-01T10:00:00+03:00'


class RoutePriceTests(WorldMixin, TestCase):
    def test_route_price_zero_or_negative_is_refused_on_update(self):
        for price in ('0', '-50', '0.00', 0, -1):
            for method in ('patch', 'put'):
                body = {'price': price}
                if method == 'put':
                    body.update(name='R1', start_point='A', end_point='B')
                r = getattr(self.api(self.mgr), method)(
                    f'/api/companies/routes/{self.r1.id}/', body, format='json')
                self.assertEqual(r.status_code, 400, (method, price, r.content[:200]))
        self.r1.refresh_from_db()
        self.assertEqual(str(self.r1.price), '100.00')

    def test_route_price_zero_is_refused_on_create(self):
        r = self.api(self.mgr).post('/api/companies/routes/create/', {
            'company_id': self.co.id, 'name': 'Z', 'start_point': 'A', 'end_point': 'B', 'price': '0'},
            format='json')
        self.assertEqual(r.status_code, 400, r.content[:200])

    def test_a_positive_price_is_still_accepted(self):
        r = self.api(self.mgr).patch(f'/api/companies/routes/{self.r1.id}/', {'price': '150.50'}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.r1.refresh_from_db()
        self.assertEqual(str(self.r1.price), '150.50')


class GarbageIdTests(WorldMixin, TestCase):
    def trip_body(self, **over):
        body = {'company_id': self.co.id, 'route_id': self.r1.id, 'driver_id': self.drv.id,
                'departure_at': FUTURE, 'capacity': 10, 'vehicle_type': 'matatu_14'}
        body.update(over)
        return body

    def test_create_trip_with_garbage_ids_is_400_not_500(self):
        for field in ('company_id', 'route_id', 'driver_id'):
            for bad in ('abc', [1], {'a': 1}, 10 ** 30, -1, 1.5):
                r = self.api(self.mgr).post('/api/companies/trips/create/',
                                            self.trip_body(**{field: bad}), format='json')
                self.assertEqual(r.status_code, 400, (field, bad, r.status_code, r.content[:200]))

    def test_create_trip_with_valid_ids_still_works(self):
        r = self.api(self.mgr).post('/api/companies/trips/create/', self.trip_body(), format='json')
        self.assertEqual(r.status_code, 201, r.content[:200])

    def test_create_route_with_a_garbage_company_id_is_400_not_500(self):
        for bad in ('abc', [1], 10 ** 30, -1):
            r = self.api(self.mgr).post('/api/companies/routes/create/', {
                'company_id': bad, 'name': 'Z', 'start_point': 'A', 'end_point': 'B', 'price': '100'},
                format='json')
            self.assertEqual(r.status_code, 400, (bad, r.status_code, r.content[:200]))


class OverflowingNumberTests(WorldMixin, TestCase):
    """1e999 is valid JSON and becomes an infinity: int() raises OverflowError."""

    def post(self, user, url, raw):
        client = self.api(user)
        client.raise_request_exception = False
        return client.post(url, raw, content_type='application/json')

    def test_set_operator_routes_answers_400_to_an_overflowing_route_id(self):
        r = self.post(self.mgr, f'/api/companies/operator-routes/{self.op_r2.pk}/',
                      '{"all_routes": false, "route_ids": [1e999]}')
        self.assertEqual(r.status_code, 400, r.content[:200])

    def test_create_schedule_answers_404_to_an_overflowing_company_id(self):
        r = self.post(self.mgr, '/api/companies/schedules/create/', '{"company_id": 1e999}')
        self.assertEqual(r.status_code, 404, r.content[:200])

    def test_create_schedule_answers_404_route_not_found_to_an_overflowing_route_id(self):
        body = f'{{"company_id": {self.co.pk}, "route_id": 1e999}}'
        r = self.post(self.mgr, '/api/companies/schedules/create/', body)
        self.assertEqual(r.status_code, 404, r.content[:200])


class RoutePriceCeilingTests(WorldMixin, TestCase):
    def test_a_price_above_the_ceiling_is_400_on_create_and_update(self):
        for price in ('100000.01', '99999999.99', '1e9'):
            r = self.api(self.mgr).post('/api/companies/routes/create/', {
                'company_id': self.co.id, 'name': 'Big', 'start_point': 'X', 'end_point': 'Y', 'price': price},
                format='json')
            self.assertEqual(r.status_code, 400, (price, r.content[:200]))
            self.assertIn('price', r.json())
            r = self.api(self.mgr).patch(f'/api/companies/routes/{self.r1.id}/', {'price': price}, format='json')
            self.assertEqual(r.status_code, 400, (price, r.content[:200]))
        self.r1.refresh_from_db()
        self.assertEqual(str(self.r1.price), '100.00')

    def test_the_ceiling_itself_is_accepted(self):
        r = self.api(self.mgr).patch(f'/api/companies/routes/{self.r1.id}/', {'price': '100000'}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:200])
