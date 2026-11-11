"""Breaker: list endpoints must not scale queries with row count."""
from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from buses.models import Bus
from companies.models import Company, Route, Trip
from drivers.models import Driver


@override_settings(SECURE_SSL_REDIRECT=False)
class NPlusOne(TestCase):
    def build(self, n, off=0):
        co = Company.objects.get_or_create(name='Co')[0]
        for i in range(off, off + n):
            r = Route.objects.create(company=co, name=f'R{i}', start_point='A', end_point='B', price=100)
            d = Driver.objects.create(name=f'D{i}', phone_number=f'07000{i:05d}', bus_number=f'K{i}', company=co)
            b = Bus.objects.create(company=co, registration_number=f'KDA {i:03d}A', bus_number=str(i), vehicle_type='matatu_14', capacity=14)
            Trip.objects.create(route=r, driver=d, bus=b, departure_at=timezone.now() + timedelta(hours=i + 1), capacity=14)

    def count(self, url):
        c = APIClient()
        with CaptureQueriesContext(connection) as q:
            r = c.get(url)
        return r.status_code, len(q)

    def test_trips_and_routes_scale(self):
        self.build(3)
        small = {u: self.count(u) for u in ('/api/companies/trips/', '/api/companies/routes/', '/api/companies/')}
        self.build(20, 10)
        big = {u: self.count(u) for u in small}
        print('NPLUS1', small, big)
        for u in small:
            self.assertLessEqual(big[u][1], small[u][1] + 3, (u, small[u], big[u]))

    def test_trip_queries_list(self):
        self.build(5)
        with CaptureQueriesContext(connection) as q:
            APIClient().get('/api/companies/trips/')
        import collections
        c = collections.Counter(x['sql'][:110] for x in q)
        print('QRY', [(k, v) for k, v in c.items() if v > 1])
