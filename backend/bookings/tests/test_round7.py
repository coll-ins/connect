import io
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from bookings.models import Booking, Payment, Payout
from bookings.tests.test_round5 import _Fixture
from companies.models import Company, Route

User = get_user_model()


@override_settings(PLATFORM_FEE_PER_SEAT=Decimal('20.00'))
class SettlementTests(_Fixture, TestCase):
    def setUp(self):
        self.build('601')
        self.n = 0

    def _paid(self, ref, settlement='eligible', refund_status='not_requested',
              refund_amount=None, method='digital', amount=Decimal('800.00'), seats=1):
        self.n += 1
        self.passenger = User.objects.create_user(
            username=f'r7_pass_{self.n}', password='password123',
            phone_number=f'+254733{self.n:06d}',
        )
        booking, payment = self.booking('confirmed', ref, payment_status='confirmed')
        Booking.objects.filter(pk=booking.pk).update(seats=seats)
        Payment.objects.filter(pk=payment.pk).update(
            settlement_status=settlement, refund_status=refund_status,
            refund_amount=refund_amount, method=method, amount=amount,
        )
        return payment

    def _settle(self, **kwargs):
        out = io.StringIO()
        call_command('settle_company', self.company.pk, stdout=out, **kwargs)
        return out.getvalue()

    def test_report_writes_nothing(self):
        p = self._paid('S1')
        output = self._settle()
        self.assertIn('NET TO PAY 780.00', output)
        self.assertEqual(Payout.objects.count(), 0)
        p.refresh_from_db()
        self.assertEqual(p.settlement_status, 'eligible')

    def test_apply_pays_only_what_is_owed(self):
        a = self._paid('S2A')                                    # 800, fee 20  -> 780
        b = self._paid('S2B', seats=2)                           # 800, fee 40  -> 760
        c = self._paid('S2C', settlement='not_ready',            # no-show: keeps 400, fee 20 -> 380
                       refund_status='processed', refund_amount=Decimal('400.00'))
        h = self._paid('S2H', settlement='not_ready',            # cheap fare: keeps 15, fee capped at 15 -> 0
                       refund_status='processed', refund_amount=Decimal('15.00'),
                       amount=Decimal('30.00'))
        not_ready = self._paid('S2D', settlement='not_ready')
        cash = self._paid('S2E', method='cash')
        held = self._paid('S2F', refund_status='processing', refund_amount=Decimal('400.00'))
        company_fault = self._paid('S2I', settlement='not_ready',
                                   refund_status='processed', refund_amount=Decimal('800.00'))

        other_company = Company.objects.create(name='R7 Other Co')
        other_route = Route.objects.create(
            company=other_company, name='R7 Other', price=Decimal('800.00')
        )
        other_booking = Booking.objects.create(
            user=self.passenger, route=other_route, trip=self.trip,
            booking_number='BKOTHER01', total_amount=Decimal('800.00'), status='confirmed',
        )
        other = Payment.objects.create(
            booking=other_booking, provider_reference='S2G', amount=Decimal('800.00'),
            method='digital', status='confirmed', settlement_status='eligible',
        )

        output = self._settle(apply=True, reference='MPESA1')
        self.assertIn('HELD BACK', output)

        payout = Payout.objects.get(reference='MPESA1')
        self.assertEqual(payout.company, self.company)
        self.assertEqual(payout.gross_amount, Decimal('2015.00'))
        self.assertEqual(payout.fee_amount, Decimal('95.00'))
        self.assertEqual(payout.net_amount, Decimal('1920.00'))
        self.assertEqual(payout.fee_per_seat, Decimal('20.00'))
        self.assertEqual(payout.payments_count, 4)

        for p in (a, b, c, h):
            p.refresh_from_db()
            self.assertEqual(p.settlement_status, 'settled')
            self.assertEqual(p.payout, payout)
        for p in (not_ready, cash, held, company_fault, other):
            p.refresh_from_db()
            self.assertIsNone(p.payout)
            self.assertNotEqual(p.settlement_status, 'settled')

    def test_second_run_pays_nothing(self):
        self._paid('S3')
        self._settle(apply=True, reference='MPESA2')
        output = self._settle(apply=True, reference='MPESA3')
        self.assertIn('Nothing to pay out', output)
        self.assertEqual(Payout.objects.count(), 1)

    def test_reference_cannot_be_reused(self):
        self._paid('S4A')
        self._settle(apply=True, reference='MPESA4')
        late = self._paid('S4B')
        with self.assertRaises(CommandError):
            self._settle(apply=True, reference='MPESA4')
        late.refresh_from_db()
        self.assertEqual(late.settlement_status, 'eligible')
        self.assertIsNone(late.payout)

    def test_apply_requires_a_reference(self):
        self._paid('S5')
        with self.assertRaises(CommandError):
            self._settle(apply=True)
        self.assertEqual(Payout.objects.count(), 0)

    def test_refuses_without_fee_setting(self):
        self._paid('S6')
        with override_settings():
            del settings.PLATFORM_FEE_PER_SEAT
            with self.assertRaises(CommandError):
                self._settle()
