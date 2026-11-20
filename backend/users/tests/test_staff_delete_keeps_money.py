"""Removing a staff account must never take that account's bookings and payments with it."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from bookings.models import Booking, Payment
from bookings.tests.test_seat_holds import SeatBase

User = get_user_model()


class StaffDeleteTests(SeatBase):
    def setUp(self):
        super().setUp()
        self.mgr = User.objects.create_user(
            username='mgr', password='pw-123456', phone_number='+254711600001',
            company=self.company, role='company_manager')
        self.op = User.objects.create_user(
            username='op', password='pw-123456', phone_number='+254711600002',
            company=self.company, role='company_operator')
        self.client = APIClient()
        self.client.force_authenticate(self.mgr)

    def test_staff_without_history_is_deleted(self):
        resp = self.client.delete(f'/api/users/company-staff/{self.op.id}/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(User.objects.filter(pk=self.op.pk).exists())

    def test_staff_with_a_paid_booking_is_deactivated_not_deleted(self):
        booking = self.booking(1, 'confirmed', user=self.op)
        payment = Payment.objects.create(
            booking=booking, amount=Decimal('100'), method='digital', status='confirmed',
            provider_reference='CONNECT-OP-1', idempotency_key='CONNECT-OP-1')
        resp = self.client.delete(f'/api/users/company-staff/{self.op.id}/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.op.refresh_from_db()
        self.assertFalse(self.op.is_active)
        self.assertTrue(Booking.objects.filter(pk=booking.pk).exists())
        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())
        self.assertIn('deactivated', resp.data['message'])
