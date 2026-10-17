from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from companies.models import Company, PickupStage, Route, Trip
from deliveries.models import Parcel
from deliveries.services import ParcelError, mark_parcel_paid
from drivers.models import Driver

User = get_user_model()
BASE = '/api/deliveries/'


class ParcelTests(APITestCase):

    def setUp(self):
        self.co_a = Company.objects.create(name='A Line', areas_served='X')
        self.co_b = Company.objects.create(name='B Line', areas_served='Y')

        def mk(username, phone, role='passenger', company=None):
            return User.objects.create_user(
                username=username, password='password123',
                phone_number=phone, role=role, company=company,
            )

        self.sender = mk('sender', '+254700000501')
        self.other = mk('other', '+254700000502')
        self.mgr_a = mk('mgr_a', '+254700000503', 'company_manager', self.co_a)
        self.mgr_b = mk('mgr_b', '+254700000504', 'company_manager', self.co_b)
        self.drv_user = mk('drv', '+254712000001', 'driver', self.co_a)
        self.drv2_user = mk('drv2', '+254712000002', 'driver', self.co_a)

        self.driver = Driver.objects.create(
            company=self.co_a, name='D1', phone_number='+254712000001', bus_number='KAA 1A')
        self.driver2 = Driver.objects.create(
            company=self.co_a, name='D2', phone_number='+254712000002', bus_number='KAA 2A')

        self.route = Route.objects.create(
            company=self.co_a, name='R', price=Decimal('500'),
            parcel_price_small=Decimal('150.00'), parcel_price_medium=Decimal('300.00'),
        )
        self.no_parcel_route = Route.objects.create(
            company=self.co_b, name='NoParcels', price=Decimal('500'))

        def stage(route, name, order):
            return PickupStage.objects.create(
                route=route, name=name, order=order,
                latitude=Decimal('-1.28'), longitude=Decimal('36.82'))

        self.s1 = stage(self.route, 'Start', 1)
        self.s2 = stage(self.route, 'End', 2)
        self.foreign = stage(self.no_parcel_route, 'Elsewhere', 1)

        self.trip = Trip.objects.create(
            route=self.route, driver=self.driver,
            departure_at=timezone.now() + timedelta(hours=5), capacity=10)

    # ---------- helpers ----------
    def body(self, **over):
        data = {
            'trip_id': self.trip.id, 'pickup_stage_id': self.s1.id,
            'dropoff_stage_id': self.s2.id, 'size': 'small',
            'description': 'Documents', 'receiver_name': 'Jane',
            'receiver_phone': '0712345678', 'no_prohibited_items': True,
        }
        data.update(over)
        return data

    def create(self, **over):
        self.client.force_authenticate(self.sender)
        return self.client.post(BASE, self.body(**over), format='json')

    def paid(self):
        r = self.create()
        p = Parcel.objects.get(id=r.data['id'])
        mark_parcel_paid(parcel_id=p.id, amount=p.price, reference=f'REF{p.id}')
        return Parcel.objects.get(id=p.id)

    def picked_up(self):
        p = self.paid()
        self.client.force_authenticate(self.drv_user)
        self.assertEqual(self.client.post(f'{BASE}{p.id}/pickup/').status_code, 200)
        return Parcel.objects.get(id=p.id)

    # ---------- creation ----------
    def test_create_ok_and_server_sets_price(self):
        r = self.create(price='1')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(r.data['price']), Decimal('150.00'))
        self.assertEqual(r.data['status'], 'pending_payment')
        self.assertEqual(len(r.data['handover_pin']), 6)

    def test_receiver_phone_normalised_and_invalid_rejected(self):
        r = self.create()
        self.assertEqual(r.data['receiver_phone'], '+254712345678')
        self.assertEqual(self.create(receiver_phone='123').status_code, 400)

    def test_size_without_rate_rejected(self):
        self.assertEqual(self.create(size='large').status_code, 400)

    def test_route_without_rates_rejected(self):
        driver_b = Driver.objects.create(
            company=self.co_b, name='DB', phone_number='+254712000099', bus_number='KBB 9B')
        trip = Trip.objects.create(
            route=self.no_parcel_route, driver=driver_b,
            departure_at=timezone.now() + timedelta(hours=5), capacity=5)
        r = self.create(trip_id=trip.id, pickup_stage_id=self.foreign.id,
                        dropoff_stage_id=self.foreign.id)
        self.assertEqual(r.status_code, 400)

    def test_stage_rules(self):
        self.assertEqual(self.create(pickup_stage_id=self.s2.id, dropoff_stage_id=self.s1.id).status_code, 400)
        self.assertEqual(self.create(dropoff_stage_id=self.s1.id).status_code, 400)
        self.assertEqual(self.create(dropoff_stage_id=self.foreign.id).status_code, 400)

    def test_trip_must_be_upcoming_and_scheduled(self):
        past = Trip.objects.create(
            route=self.route, driver=self.driver,
            departure_at=timezone.now() - timedelta(hours=1), capacity=5)
        self.assertEqual(self.create(trip_id=past.id).status_code, 400)
        self.trip.status = 'cancelled'
        self.trip.save()
        self.assertEqual(self.create().status_code, 400)

    def test_prohibited_items_must_be_confirmed(self):
        self.assertEqual(self.create(no_prohibited_items=False).status_code, 400)

    def test_unpaid_limit(self):
        for _ in range(5):
            self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create().status_code, 429)

    def test_anonymous_blocked(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(BASE).status_code, (401, 403))

    # ---------- visibility ----------
    def test_visibility_rules(self):
        pid = self.create().data['id']
        url = f'{BASE}{pid}/'

        self.client.force_authenticate(self.sender)
        self.assertIn('handover_pin', self.client.get(url).data)

        for user in (self.drv_user, self.mgr_a):
            self.client.force_authenticate(user)
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertNotIn('handover_pin', r.data)

        for user in (self.other, self.mgr_b, self.drv2_user):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_company_list_is_scoped(self):
        self.paid()
        self.client.force_authenticate(self.mgr_a)
        self.assertEqual(len(self.client.get(f'{BASE}company/').data), 1)
        self.client.force_authenticate(self.mgr_b)
        self.assertEqual(len(self.client.get(f'{BASE}company/').data), 0)
        self.client.force_authenticate(self.sender)
        self.assertEqual(self.client.get(f'{BASE}company/').status_code, 403)

    # ---------- payment ----------
    def test_payment_rules(self):
        p = Parcel.objects.get(id=self.create().data['id'])
        with self.assertRaises(ParcelError):
            mark_parcel_paid(parcel_id=p.id, amount=Decimal('1.00'), reference='X1')
        _, changed = mark_parcel_paid(parcel_id=p.id, amount=p.price, reference='X2')
        self.assertTrue(changed)
        _, changed = mark_parcel_paid(parcel_id=p.id, amount=p.price, reference='X2')
        self.assertFalse(changed)
        with self.assertRaises(ParcelError):
            mark_parcel_paid(parcel_id=p.id, amount=p.price, reference='OTHER')

    # ---------- pickup ----------
    def test_cannot_pick_up_unpaid(self):
        pid = self.create().data['id']
        self.client.force_authenticate(self.drv_user)
        self.assertEqual(self.client.post(f'{BASE}{pid}/pickup/').status_code, 409)

    def test_only_the_trips_driver_can_pick_up(self):
        p = self.paid()
        self.client.force_authenticate(self.drv2_user)
        self.assertEqual(self.client.post(f'{BASE}{p.id}/pickup/').status_code, 404)
        self.client.force_authenticate(self.sender)
        self.assertEqual(self.client.post(f'{BASE}{p.id}/pickup/').status_code, 403)
        self.client.force_authenticate(self.drv_user)
        self.assertEqual(self.client.post(f'{BASE}{p.id}/pickup/').status_code, 200)
        self.assertEqual(self.client.post(f'{BASE}{p.id}/pickup/').status_code, 409)

    # ---------- delivery ----------
    def test_delivery_requires_correct_pin(self):
        p = self.picked_up()
        self.client.force_authenticate(self.drv_user)
        wrong = '000000' if p.handover_pin != '000000' else '111111'
        self.assertEqual(self.client.post(f'{BASE}{p.id}/deliver/', {'pin': wrong}, format='json').status_code, 400)
        self.assertEqual(self.client.post(f'{BASE}{p.id}/deliver/', {'pin': 'abc'}, format='json').status_code, 400)
        r = self.client.post(f'{BASE}{p.id}/deliver/', {'pin': p.handover_pin}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['status'], 'delivered')
        self.assertEqual(self.client.post(f'{BASE}{p.id}/deliver/', {'pin': p.handover_pin}, format='json').status_code, 409)

    def test_pin_locks_after_five_wrong_attempts(self):
        p = self.picked_up()
        self.client.force_authenticate(self.drv_user)
        wrong = '000000' if p.handover_pin != '000000' else '111111'
        for _ in range(5):
            self.assertEqual(self.client.post(f'{BASE}{p.id}/deliver/', {'pin': wrong}, format='json').status_code, 400)
        r = self.client.post(f'{BASE}{p.id}/deliver/', {'pin': p.handover_pin}, format='json')
        self.assertEqual(r.status_code, 423)
        self.assertEqual(Parcel.objects.get(id=p.id).status, 'picked_up')

    def test_cannot_deliver_before_pickup(self):
        p = self.paid()
        self.client.force_authenticate(self.drv_user)
        r = self.client.post(f'{BASE}{p.id}/deliver/', {'pin': p.handover_pin}, format='json')
        self.assertEqual(r.status_code, 409)

    # ---------- cancel ----------
    def test_cancel_rules(self):
        pid = self.create().data['id']
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(f'{BASE}{pid}/cancel/').status_code, 404)
        self.client.force_authenticate(self.sender)
        self.assertEqual(self.client.post(f'{BASE}{pid}/cancel/').status_code, 200)
        self.assertEqual(self.client.post(f'{BASE}{pid}/cancel/').status_code, 409)

    def test_paid_parcel_cancel_queues_full_refund(self):
        p = self.paid()
        self.client.force_authenticate(self.sender)
        response = self.client.post(f'{BASE}{p.id}/cancel/')
        self.assertEqual(response.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.status, 'cancelled')
        from bookings.models import UnappliedPayment
        self.assertEqual(
            UnappliedPayment.objects.filter(
                reference=p.provider_reference, status='refund_due').count(), 1)

    # ---------- driver list ----------
    def test_driver_list_only_own_paid_parcels(self):
        self.paid()
        self.create()
        self.client.force_authenticate(self.drv_user)
        self.assertEqual(len(self.client.get(f'{BASE}driver/').data), 1)
        self.client.force_authenticate(self.drv2_user)
        self.assertEqual(len(self.client.get(f'{BASE}driver/').data), 0)
        self.client.force_authenticate(self.sender)
        self.assertEqual(self.client.get(f'{BASE}driver/').status_code, 403)
