from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import UnappliedPayment
from charters.models import CharterRequest
from charters.tests.test_charters import BASE, CharterTests as _Base
from companies.models import Route, Trip


class PaidHireCancellationTests(APITestCase):
    # Reuse the hire fixture without re-running its tests.
    setUp, body, make, quote, quoted, confirmed = (
        _Base.setUp, _Base.body, _Base.make, _Base.quote, _Base.quoted, _Base.confirmed)

    def _cancel(self, c, user):
        self.client.force_authenticate(user)
        return self.client.post(f'{BASE}{c.id}/cancel/')

    def test_customer_cancel_48h_ahead_is_refunded_in_full(self):
        c = self.confirmed()  # departs in 3 days
        r = self._cancel(c, self.pax)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['status'], 'cancelled')
        row = UnappliedPayment.objects.get(reference=c.provider_reference)
        self.assertEqual((row.kind, row.status, row.amount), ('charter', 'refund_due', c.quote_price))

    def test_customer_cannot_cancel_inside_48h(self):
        c = self.confirmed()
        CharterRequest.objects.filter(pk=c.pk).update(depart_at=timezone.now() + timedelta(hours=30))
        r = self._cancel(c, self.pax)
        self.assertEqual(r.status_code, 409)
        self.assertIn('A Line', r.data['error'])
        self.assertFalse(UnappliedPayment.objects.exists())

    def test_company_cancel_refunds_in_full_and_needs_a_reason(self):
        c = self.confirmed()
        self.client.force_authenticate(self.mgr_a)
        url = f'{BASE}{c.id}/company-cancel/'
        self.assertEqual(self.client.post(url, {}).status_code, 400)
        r = self.client.post(url, {'reason': 'Bus broke down'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(UnappliedPayment.objects.filter(
            reference=c.provider_reference, status='refund_due').exists())

    def test_other_company_and_passenger_cannot_company_cancel(self):
        c = self.confirmed()
        for user in (self.mgr_b, self.pax, self.op_a):
            self.client.force_authenticate(user)
            r = self.client.post(f'{BASE}{c.id}/company-cancel/', {'reason': 'x'}, format='json')
            self.assertIn(r.status_code, (403, 404), user.username)
        self.assertFalse(UnappliedPayment.objects.exists())

    def test_driver_with_a_scheduled_trip_cannot_be_hired(self):
        cid = self.make().data['id']
        route = Route.objects.create(company=self.a, name='R', price=500)
        Trip.objects.create(route=route, driver=self.drv_a, capacity=14,
                            departure_at=timezone.now() + timedelta(days=3, hours=2))
        r = self.quote(cid, driver=self.drv_a)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.quote(cid, driver=self.drv_a2).status_code, 200)
