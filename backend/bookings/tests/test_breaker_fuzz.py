import json
"""Breaker: fuzz every POST/PATCH/PUT endpoint with hostile bodies; none may 500."""
import re
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import get_resolver
from rest_framework.test import APIClient
from companies.models import Company

KEYS = ['trip_id','route_id','company_id','driver_id','bus_id','booking_id','seat_number','seat_numbers','amount','latitude','longitude','schedule_id','delivery_id','parcel_id','charter_id','pickup_stage_id','dropoff_stage_id','passengers','seats','count','page','limit','id','quantity']
BODIES = [json.dumps({k: 'abc' for k in KEYS}), json.dumps({k: 99999999999999999999999 for k in KEYS}), json.dumps({k: {'a':1} for k in KEYS}), json.dumps({k: -1 for k in KEYS}), json.dumps({k: '' for k in KEYS}),
          '{"trip_id": 1e999, "route_id": 1e999, "company_id": 1e999, "driver_id": 1e999, "bus_id": 1e999, "amount": 1e999, "seats": "a", "latitude": "x", "longitude": [], "vehicle_type": {}}',
          '{"trip_id": {}, "route_id": [], "company_id": {}, "amount": -5, "seat_numbers": "x", "phone_number": 5, "latitude": 1e999, "longitude": NaN}']

def walk(patterns, prefix=''):
    for p in patterns:
        s = prefix + str(p.pattern)
        if hasattr(p, 'url_patterns'):
            yield from walk(p.url_patterns, s)
        else:
            yield s

def fill(s):
    s = re.sub(r'\(\?P<\w+>[^)]*\)', '1', s)
    s = re.sub(r'<(?:int:)?\w+>', '1', s)
    s = re.sub(r'<\w+:\w+>', '1', s)
    return '/' + s.replace('^', '').replace('$', '').replace('\\Z', '')

from collections import Counter

@override_settings(SECURE_SSL_REDIRECT=False)
class Fuzz(TestCase):
    def test_fuzz(self):
        from unittest import mock
        import logging
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        throttle = mock.patch('rest_framework.throttling.SimpleRateThrottle.allow_request', return_value=True)
        throttle.start()
        self.addCleanup(throttle.stop)
        U = get_user_model()
        co = Company.objects.create(name='C')
        roles = ['passenger', 'driver', 'company_manager', 'company_operator', 'admin']
        bad = []
        self.cnt = Counter()
        urls = sorted(set(fill(s) for s in walk(get_resolver().url_patterns)))
        for role in roles:
            try:
                u = U.objects.create(username=f'u{role}', role=role, company=co, phone_number='0700000009' if role=='x' else None) if hasattr(U,'role') else U.objects.create(username=f'u{role}')
            except Exception as e:
                u = U.objects.create(username=f'u{role}')
            c = APIClient(raise_request_exception=False)
            c.force_authenticate(user=u)
            for url in urls:
                if '<' in url or '(' in url or 'admin/' in url[:8]: continue
                for b in BODIES:
                    for m in ('post', 'patch'):
                        r = getattr(c, m)(url, b, content_type='application/json')
                        self.cnt[r.status_code] += 1
                        if r.status_code >= 500:
                            bad.append((role, m, url, b[:30], r.status_code))
        seen = {}
        for role, m, url, b, code in bad:
            pass
        for role, m, url, b, code in bad:
            seen.setdefault((m, url, b), []).append(role)
        print('\nFUZZ500', len(seen), dict(self.cnt), len(urls))
        for k, v in seen.items():
            print('FUZZ500', k, sorted(set(v)))
        self.assertEqual(len(seen), 0)
