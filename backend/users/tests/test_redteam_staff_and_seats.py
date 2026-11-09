from datetime import timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()


class BreakerRegressionTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.co = Company.objects.create(name='A', areas_served='x')
        self.route = Route.objects.create(company=self.co, name='R', start_point='A', end_point='B', price=Decimal('100'))
        self.stage = PickupStage.objects.create(route=self.route, name='S1', latitude=Decimal('-1.285'), longitude=Decimal('36.82'), order=1)
        d = Driver.objects.create(name='D', phone_number='+254711000000', bus_number='K1', company=self.co)
        self.trip = Trip.objects.create(route=self.route, driver=d, capacity=14, status='scheduled',
                                        departure_at=timezone.now() + timedelta(hours=3))

    def _u(self, n):
        return User.objects.create_user(username=f'u{n}', password='pw-123456x', phone_number=f'+2547200000{n:02d}')

    def test_one_account_cannot_hold_a_whole_bus_unpaid(self):
        a, b = self._u(1), self._u(2)
        ca = APIClient(); ca.force_authenticate(a)
        r = ca.post('/api/bookings/create/', {'trip_id': self.trip.id, 'seats': 14, 'pickup_stage_id': self.stage.id}, format='json')
        self.assertEqual(r.status_code, 400)
        r = ca.post('/api/bookings/create/', {'trip_id': self.trip.id, 'seats': 10, 'pickup_stage_id': self.stage.id}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        r = ca.post('/api/bookings/create/', {'trip_id': self.trip.id, 'seats': 1, 'pickup_stage_id': self.stage.id}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('unpaid seats', r.data['error'])
        cb = APIClient(); cb.force_authenticate(b)
        r = cb.post('/api/bookings/create/', {'trip_id': self.trip.id, 'seats': 1, 'pickup_stage_id': self.stage.id}, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_staff_patch_dup_phone_variant(self):
        self._u(5)  # already holds +254720000005
        mgr = User.objects.create_user(username='m', password='pw-123456x', phone_number='+254733000001', role='company_manager', company=self.co)
        st = User.objects.create_user(username='s', password='pw-123456x', phone_number='+254733000002', role='company_operator', company=self.co)
        c = APIClient(); c.force_authenticate(mgr)
        c.raise_request_exception = False
        r = c.patch(f'/api/users/company-staff/{st.id}/', {'phone_number': '0720000005'}, format='json')
        self.assertEqual(r.status_code, 400, r.status_code)  # 500 / IntegrityError = bug

    def test_manager_resets_peer_manager_password(self):
        m1 = User.objects.create_user(username='m1', password='pw-123456x', phone_number='+254733000011', role='company_manager', company=self.co)
        m2 = User.objects.create_user(username='m2', password='pw-123456x', phone_number='+254733000012', role='company_manager', company=self.co)
        c = APIClient(); c.force_authenticate(m1)
        r = c.patch(f'/api/users/company-staff/{m2.id}/', {'password': 'Attacker-9911x'}, format='json')
        m2.refresh_from_db()
        self.assertFalse(m2.check_password('Attacker-9911x'), r.status_code)
