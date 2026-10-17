from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from companies.models import Company, PickupStage, Route, Trip
from deliveries.models import Parcel
from deliveries.services import mark_parcel_paid
from drivers.models import Driver

User = get_user_model()
BASE = '/api/deliveries/'


class CompanyIsolationTests(APITestCase):

    def setUp(self):
        self.a = Company.objects.create(name='A Line', areas_served='X')
        self.b = Company.objects.create(name='B Line', areas_served='Y')

        def mk(username, phone, role='passenger', company=None):
            return User.objects.create_user(
                username=username, password='password123',
                phone_number=phone, role=role, company=company)

        self.sender = mk('s', '+254700000601')
        self.sender_b = mk('sb', '+254700000602')
        self.mgr_a = mk('ma', '+254700000603', 'company_manager', self.a)
        self.mgr_b = mk('mb', '+254700000604', 'company_manager', self.b)
        self.op_b = mk('ob', '+254700000605', 'company_operator', self.b)
        self.drv_a_user = mk('da', '+254712000011', 'driver', self.a)
        self.drv_b_user = mk('db', '+254712000012', 'driver', self.b)

        self.drv_a = Driver.objects.create(
            company=self.a, name='DA', phone_number='+254712000011', bus_number='KA 1')
        self.drv_b = Driver.objects.create(
            company=self.b, name='DB', phone_number='+254712000012', bus_number='KB 1')

        def route(company):
            r = Route.objects.create(company=company, name='R', price=Decimal('500'),
                                     parcel_price_small=Decimal('100'))
            s1 = PickupStage.objects.create(route=r, name='S1', order=1,
                                            latitude=Decimal('-1.2'), longitude=Decimal('36.8'))
            s2 = PickupStage.objects.create(route=r, name='S2', order=2,
                                            latitude=Decimal('-1.3'), longitude=Decimal('36.9'))
            return r, s1, s2

        self.ra, self.a1, self.a2 = route(self.a)
        self.rb, self.b1, self.b2 = route(self.b)
        when = timezone.now() + timedelta(hours=5)
        self.trip_a = Trip.objects.create(route=self.ra, driver=self.drv_a, departure_at=when, capacity=5)
        self.trip_b = Trip.objects.create(route=self.rb, driver=self.drv_b, departure_at=when, capacity=5)

    def make_parcel(self, sender, trip, s1, s2):
        self.client.force_authenticate(sender)
        r = self.client.post(BASE, {
            'trip_id': trip.id, 'pickup_stage_id': s1.id, 'dropoff_stage_id': s2.id,
            'size': 'small', 'description': 'Box', 'receiver_name': 'R',
            'receiver_phone': '0712345678', 'no_prohibited_items': True,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        p = Parcel.objects.get(id=r.data['id'])
        mark_parcel_paid(parcel_id=p.id, amount=p.price, reference=f'R{p.id}')
        return Parcel.objects.get(id=p.id)

    def test_company_b_staff_see_nothing_of_company_a(self):
        pa = self.make_parcel(self.sender, self.trip_a, self.a1, self.a2)
        for user in (self.mgr_b, self.op_b):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(f'{BASE}{pa.id}/').status_code, 404)
            self.assertEqual(self.client.get(f'{BASE}company/').data, [])

    def test_each_company_lists_only_its_own(self):
        self.make_parcel(self.sender, self.trip_a, self.a1, self.a2)
        pb = self.make_parcel(self.sender_b, self.trip_b, self.b1, self.b2)
        self.client.force_authenticate(self.mgr_b)
        ids = [p['id'] for p in self.client.get(f'{BASE}company/').data]
        self.assertEqual(ids, [pb.id])

    def test_other_companys_driver_cannot_see_or_handle_parcel(self):
        pa = self.make_parcel(self.sender, self.trip_a, self.a1, self.a2)
        self.client.force_authenticate(self.drv_b_user)
        self.assertEqual(self.client.get(f'{BASE}{pa.id}/').status_code, 404)
        self.assertEqual(self.client.post(f'{BASE}{pa.id}/pickup/').status_code, 404)
        self.assertEqual(self.client.get(f'{BASE}driver/').data, [])

    def test_senders_cannot_see_each_others_parcels(self):
        pa = self.make_parcel(self.sender, self.trip_a, self.a1, self.a2)
        self.client.force_authenticate(self.sender_b)
        self.assertEqual(self.client.get(f'{BASE}{pa.id}/').status_code, 404)
        self.assertEqual(self.client.get(BASE).data, [])

    def test_staff_and_driver_never_receive_the_pin(self):
        pa = self.make_parcel(self.sender, self.trip_a, self.a1, self.a2)
        for user in (self.mgr_a, self.drv_a_user):
            self.client.force_authenticate(user)
            r = self.client.get(f'{BASE}{pa.id}/')
            self.assertEqual(r.status_code, 200)
            self.assertNotIn('handover_pin', r.data)

    def test_trip_with_other_companys_driver_is_refused(self):
        bad = Trip.objects.create(route=self.ra, driver=self.drv_b,
                                  departure_at=timezone.now() + timedelta(hours=6), capacity=5)
        self.client.force_authenticate(self.sender)
        r = self.client.post(BASE, {
            'trip_id': bad.id, 'pickup_stage_id': self.a1.id, 'dropoff_stage_id': self.a2.id,
            'size': 'small', 'description': 'Box', 'receiver_name': 'R',
            'receiver_phone': '0712345678', 'no_prohibited_items': True,
        }, format='json')
        self.assertEqual(r.status_code, 409)
