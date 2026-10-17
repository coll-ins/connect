from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from charters.models import CharterRequest
from charters.services import CharterError, mark_charter_paid
from companies.models import Company
from drivers.models import Driver

User = get_user_model()
BASE = '/api/charters/'


class CharterTests(APITestCase):

    def setUp(self):
        self.a = Company.objects.create(name='A Line', areas_served='X', accepts_charters=True)
        self.b = Company.objects.create(name='B Line', areas_served='Y', accepts_charters=True)
        self.closed = Company.objects.create(name='Closed', areas_served='Z')

        def mk(username, phone, role='passenger', company=None):
            return User.objects.create_user(
                username=username, password='password123',
                phone_number=phone, role=role, company=company)

        self.pax = mk('pax', '+254700000701')
        self.pax2 = mk('pax2', '+254700000702')
        self.mgr_a = mk('mga', '+254700000703', 'company_manager', self.a)
        self.mgr_b = mk('mgb', '+254700000704', 'company_manager', self.b)
        self.op_a = mk('opa', '+254700000705', 'company_operator', self.a)
        self.drv_a_user = mk('da', '+254712000021', 'driver', self.a)
        self.drv_a2_user = mk('da2', '+254712000022', 'driver', self.a)
        self.drv_b_user = mk('db', '+254712000023', 'driver', self.b)

        self.drv_a = Driver.objects.create(
            company=self.a, name='DA', phone_number='+254712000021', bus_number='KA 1')
        self.drv_a2 = Driver.objects.create(
            company=self.a, name='DA2', phone_number='+254712000022', bus_number='KA 2')
        self.drv_b = Driver.objects.create(
            company=self.b, name='DB', phone_number='+254712000023', bus_number='KB 1')

    # ---------- helpers ----------
    def body(self, **over):
        data = {
            'company_id': self.a.id, 'purpose': 'School trip',
            'pickup_location': 'Karen', 'destination': 'Nakuru',
            'depart_at': (timezone.now() + timedelta(days=3)).isoformat(),
            'passenger_count': 40, 'contact_name': 'Teacher',
            'contact_phone': '0712345678',
        }
        data.update(over)
        return data

    def make(self, user=None, **over):
        self.client.force_authenticate(user or self.pax)
        return self.client.post(BASE, self.body(**over), format='json')

    def quote(self, cid, user=None, price='20000.00', driver=None, hours=48):
        self.client.force_authenticate(user or self.mgr_a)
        return self.client.post(f'{BASE}{cid}/quote/', {
            'price': price, 'driver_id': (driver or self.drv_a).id,
            'valid_hours': hours}, format='json')

    def quoted(self, **kw):
        cid = self.make().data['id']
        self.assertEqual(self.quote(cid, **kw).status_code, 200)
        return CharterRequest.objects.get(id=cid)

    def confirmed(self):
        c = self.quoted()
        mark_charter_paid(charter_id=c.id, amount=c.quote_price, reference=f'R{c.id}')
        return CharterRequest.objects.get(id=c.id)

    # ---------- creation ----------
    def test_create_ok(self):
        r = self.make()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['status'], 'requested')
        self.assertEqual(r.data['contact_phone'], '+254712345678')
        self.assertIsNone(r.data['quote_price'])

    def test_company_must_accept_charters(self):
        self.assertEqual(self.make(company_id=self.closed.id).status_code, 404)
        self.assertEqual(self.make(company_id=99999).status_code, 404)

    def test_date_rules(self):
        soon = (timezone.now() + timedelta(hours=2)).isoformat()
        self.assertEqual(self.make(depart_at=soon).status_code, 400)
        dep = timezone.now() + timedelta(days=3)
        self.assertEqual(self.make(
            depart_at=dep.isoformat(), return_at=(dep - timedelta(hours=1)).isoformat()
        ).status_code, 400)
        self.assertEqual(self.make(
            depart_at=dep.isoformat(), return_at=(dep + timedelta(days=30)).isoformat()
        ).status_code, 400)

    def test_input_rules(self):
        self.assertEqual(self.make(contact_phone='123').status_code, 400)
        self.assertEqual(self.make(passenger_count=0).status_code, 400)
        self.assertEqual(self.make(passenger_count=9999).status_code, 400)

    def test_open_request_limit(self):
        for _ in range(5):
            self.assertEqual(self.make().status_code, 201)
        self.assertEqual(self.make().status_code, 429)

    def test_anonymous_blocked(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(BASE).status_code, (401, 403))

    # ---------- company isolation ----------
    def test_other_company_staff_see_nothing(self):
        cid = self.make().data['id']
        self.client.force_authenticate(self.mgr_b)
        self.assertEqual(self.client.get(f'{BASE}{cid}/').status_code, 404)
        self.assertEqual(self.client.get(f'{BASE}company/').data, [])
        self.assertEqual(self.quote(cid, user=self.mgr_b, driver=self.drv_b).status_code, 404)
        self.client.post(f'{BASE}{cid}/decline/', {'reason': 'x'}, format='json')
        self.assertEqual(CharterRequest.objects.get(id=cid).status, 'requested')

    def test_each_company_lists_only_its_own(self):
        mine = self.make().data['id']
        theirs = self.make(company_id=self.b.id).data['id']
        self.client.force_authenticate(self.mgr_a)
        self.assertEqual([c['id'] for c in self.client.get(f'{BASE}company/').data], [mine])
        self.client.force_authenticate(self.mgr_b)
        self.assertEqual([c['id'] for c in self.client.get(f'{BASE}company/').data], [theirs])

    def test_passengers_cannot_see_each_others(self):
        cid = self.make().data['id']
        self.client.force_authenticate(self.pax2)
        self.assertEqual(self.client.get(f'{BASE}{cid}/').status_code, 404)
        self.assertEqual(self.client.get(BASE).data, [])
        self.assertEqual(self.client.post(f'{BASE}{cid}/cancel/').status_code, 404)

    def test_only_managers_can_quote_or_decline(self):
        cid = self.make().data['id']
        self.assertEqual(self.quote(cid, user=self.op_a).status_code, 403)
        self.assertEqual(self.quote(cid, user=self.pax).status_code, 403)
        self.client.force_authenticate(self.op_a)
        self.assertEqual(self.client.post(f'{BASE}{cid}/decline/', {'reason': 'x'}, format='json').status_code, 403)
        self.assertEqual(self.client.get(f'{BASE}{cid}/').status_code, 200)

    def test_staff_see_account_details_driver_does_not(self):
        c = self.confirmed()
        self.client.force_authenticate(self.mgr_a)
        self.assertIn('passenger_account', self.client.get(f'{BASE}{c.id}/').data)
        self.client.force_authenticate(self.drv_a_user)
        r = self.client.get(f'{BASE}{c.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('passenger_account', r.data)

    # ---------- quoting ----------
    def test_quote_with_other_companys_driver_refused(self):
        cid = self.make().data['id']
        self.assertEqual(self.quote(cid, driver=self.drv_b).status_code, 400)

    def test_quote_validation(self):
        cid = self.make().data['id']
        self.assertEqual(self.quote(cid, price='0').status_code, 400)
        self.assertEqual(self.quote(cid, hours=0).status_code, 400)
        self.assertEqual(self.quote(cid, hours=500).status_code, 400)

    def test_quote_sets_price_server_side_and_is_revisable(self):
        cid = self.make().data['id']
        r = self.quote(cid, price='15000')
        self.assertEqual(r.data['status'], 'quoted')
        self.assertEqual(Decimal(r.data['quote_price']), Decimal('15000.00'))
        self.assertEqual(self.quote(cid, price='18000').status_code, 200)

    def test_cannot_quote_after_decline(self):
        cid = self.make().data['id']
        self.client.force_authenticate(self.mgr_a)
        r = self.client.post(f'{BASE}{cid}/decline/', {'reason': 'No bus free'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.quote(cid).status_code, 409)

    def test_decline_needs_reason(self):
        cid = self.make().data['id']
        self.client.force_authenticate(self.mgr_a)
        self.assertEqual(self.client.post(f'{BASE}{cid}/decline/', {}, format='json').status_code, 400)

    # ---------- payment ----------
    def test_payment_rules(self):
        c = self.quoted()
        with self.assertRaises(CharterError):
            mark_charter_paid(charter_id=c.id, amount=Decimal('1.00'), reference='X1')
        _, changed = mark_charter_paid(charter_id=c.id, amount=c.quote_price, reference='X2')
        self.assertTrue(changed)
        _, changed = mark_charter_paid(charter_id=c.id, amount=c.quote_price, reference='X2')
        self.assertFalse(changed)
        with self.assertRaises(CharterError):
            mark_charter_paid(charter_id=c.id, amount=c.quote_price, reference='OTHER')

    def test_expired_quote_cannot_be_paid_and_shows_expired(self):
        c = self.quoted()
        CharterRequest.objects.filter(id=c.id).update(
            quote_valid_until=timezone.now() - timedelta(minutes=1))
        with self.assertRaises(CharterError):
            mark_charter_paid(charter_id=c.id, amount=c.quote_price, reference='LATE')
        self.client.force_authenticate(self.pax)
        self.assertEqual(self.client.get(f'{BASE}{c.id}/').data['status'], 'expired')

    def test_unquoted_request_cannot_be_paid(self):
        cid = self.make().data['id']
        with self.assertRaises(CharterError):
            mark_charter_paid(charter_id=cid, amount=Decimal('100'), reference='N1')

    def test_double_booking_blocked_at_payment(self):
        c1 = self.quoted()
        c2 = self.quoted()
        mark_charter_paid(charter_id=c1.id, amount=c1.quote_price, reference='D1')
        with self.assertRaises(CharterError) as ctx:
            mark_charter_paid(charter_id=c2.id, amount=c2.quote_price, reference='D2')
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(CharterRequest.objects.get(id=c2.id).status, 'quoted')

    def test_confirmed_booking_blocks_new_quote_for_same_driver(self):
        self.confirmed()
        cid = self.make().data['id']
        self.assertEqual(self.quote(cid, driver=self.drv_a).status_code, 409)
        self.assertEqual(self.quote(cid, driver=self.drv_a2).status_code, 200)

    # ---------- cancel ----------
    def test_cancel_rules(self):
        cid = self.make().data['id']
        self.client.force_authenticate(self.pax)
        self.assertEqual(self.client.post(f'{BASE}{cid}/cancel/').status_code, 200)
        self.assertEqual(self.client.post(f'{BASE}{cid}/cancel/').status_code, 409)

    def test_paid_hire_cannot_be_cancelled_yet(self):
        c = self.confirmed()
        self.client.force_authenticate(self.pax)
        self.assertEqual(self.client.post(f'{BASE}{c.id}/cancel/').status_code, 409)

    # ---------- driver ----------
    def test_driver_sees_only_own_confirmed_jobs(self):
        self.quoted()
        c = self.confirmed()
        self.client.force_authenticate(self.drv_a_user)
        self.assertEqual([x['id'] for x in self.client.get(f'{BASE}driver/').data], [c.id])
        self.assertEqual(self.client.get(f'{BASE}{c.id}/').status_code, 200)
        for other in (self.drv_a2_user, self.drv_b_user):
            self.client.force_authenticate(other)
            self.assertEqual(self.client.get(f'{BASE}driver/').data, [])
            self.assertEqual(self.client.get(f'{BASE}{c.id}/').status_code, 404)
        self.client.force_authenticate(self.pax)
        self.assertEqual(self.client.get(f'{BASE}driver/').status_code, 403)

    def test_driver_cannot_see_unpaid_request(self):
        c = self.quoted()
        self.client.force_authenticate(self.drv_a_user)
        self.assertEqual(self.client.get(f'{BASE}{c.id}/').status_code, 404)

    # ---------- completion ----------
    def test_completion_rules(self):
        c = self.confirmed()
        self.client.force_authenticate(self.drv_a_user)
        self.assertEqual(self.client.post(f'{BASE}{c.id}/complete/').status_code, 409)
        CharterRequest.objects.filter(id=c.id).update(depart_at=timezone.now() - timedelta(hours=2))
        self.client.force_authenticate(self.drv_a2_user)
        self.assertEqual(self.client.post(f'{BASE}{c.id}/complete/').status_code, 404)
        self.client.force_authenticate(self.drv_a_user)
        r = self.client.post(f'{BASE}{c.id}/complete/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['status'], 'completed')
        self.assertEqual(self.client.post(f'{BASE}{c.id}/complete/').status_code, 409)

    # ---------- listing of companies ----------
    def test_only_opted_in_companies_are_listed(self):
        self.client.force_authenticate(self.pax)
        names = [c['name'] for c in self.client.get(f'{BASE}companies/').data]
        self.assertEqual(names, ['A Line', 'B Line'])
