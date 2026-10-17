import io
from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import Booking, Payment, Payout, PayoutItem
from bookings.tests.test_round5 import _Fixture
from charters.models import CharterRequest
from companies.models import Company

FEES = dict(
    PLATFORM_FEE_PER_SEAT=Decimal('20.00'),
    PLATFORM_CHARTER_FEE_PERCENT=Decimal('10.00'),
)


@override_settings(**FEES)
class CharterSettlementTests(_Fixture, TestCase):
    def setUp(self):
        self.build('801')

    def _charter(self, ref, status='completed', price=Decimal('30000.00'), company=None):
        return CharterRequest.objects.create(
            passenger=self.passenger, company=company or self.company, driver=self.driver,
            purpose='Wedding', pickup_location='CBD', destination='Nakuru',
            depart_at=timezone.now() + timedelta(days=5), passenger_count=14,
            contact_name='Test', contact_phone='+254700000000',
            status=status, quote_price=price, provider_reference=ref,
        )

    def _settle(self, **kwargs):
        out = io.StringIO()
        call_command('settle_company', self.company.pk, stdout=out, **kwargs)
        return out.getvalue()

    def test_completed_charter_is_paid_with_percentage_fee(self):
        charter = self._charter('CHT-R10-1')
        output = self._settle()
        self.assertIn('NET TO PAY 27000.00', output)
        self.assertEqual(Payout.objects.count(), 0)

        self._settle(apply=True, reference='MPESA-C1')
        payout = Payout.objects.get(reference='MPESA-C1')
        self.assertEqual(payout.gross_amount, Decimal('30000.00'))
        self.assertEqual(payout.fee_amount, Decimal('3000.00'))
        self.assertEqual(payout.net_amount, Decimal('27000.00'))
        self.assertEqual(payout.breakdown['charters']['count'], 1)
        item = PayoutItem.objects.get(kind='charter', object_id=charter.pk)
        self.assertEqual(item.net_amount, Decimal('27000.00'))

    def test_only_completed_paid_charters_of_this_company_are_paid(self):
        self._charter('CHT-R10-OK')
        self._charter('CHT-R10-CONF', status='confirmed')
        self._charter('CHT-R10-CANC', status='cancelled')
        self._charter(None)
        other = Company.objects.create(name='R10 Other Co')
        self._charter('CHT-R10-OTHER', company=other)

        self._settle(apply=True, reference='MPESA-C2')
        self.assertEqual(PayoutItem.objects.count(), 1)
        self.assertEqual(PayoutItem.objects.get().reference, 'CHT-R10-OK')

    def test_a_charter_is_never_paid_twice(self):
        self._charter('CHT-R10-2')
        self._settle(apply=True, reference='MPESA-C3')
        output = self._settle(apply=True, reference='MPESA-C4')
        self.assertIn('Nothing to pay out', output)
        self.assertEqual(PayoutItem.objects.count(), 1)
        self.assertEqual(Payout.objects.count(), 1)

    def test_charter_paid_by_another_run_is_skipped(self):
        charter = self._charter('CHT-R10-3')
        earlier = Payout.objects.create(
            company=self.company, reference='EARLIER', gross_amount=1, fee_per_seat=0,
            fee_amount=0, net_amount=1, payments_count=1,
        )
        PayoutItem.objects.create(
            payout=earlier, kind='charter', object_id=charter.pk, reference='x',
            gross_amount=1, fee_amount=0, net_amount=1,
        )
        self.assertIn('Nothing to pay out', self._settle(apply=True, reference='MPESA-C5'))

    def test_database_refuses_a_double_payout_of_the_same_charter(self):
        charter = self._charter('CHT-R10-4')
        first = Payout.objects.create(
            company=self.company, reference='P1', gross_amount=1, fee_per_seat=0,
            fee_amount=0, net_amount=1, payments_count=1,
        )
        second = Payout.objects.create(
            company=self.company, reference='P2', gross_amount=1, fee_per_seat=0,
            fee_amount=0, net_amount=1, payments_count=1,
        )
        kwargs = dict(kind='charter', object_id=charter.pk, reference='x',
                      gross_amount=1, fee_amount=0, net_amount=1)
        PayoutItem.objects.create(payout=first, **kwargs)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PayoutItem.objects.create(payout=second, **kwargs)

    def test_seats_and_charters_settle_in_one_payout(self):
        booking, payment = self.booking('confirmed', 'S10', payment_status='confirmed')
        Booking.objects.filter(pk=booking.pk).update(seats=1)
        Payment.objects.filter(pk=payment.pk).update(settlement_status='eligible')
        self._charter('CHT-R10-5')

        self._settle(apply=True, reference='MPESA-C6')
        payout = Payout.objects.get(reference='MPESA-C6')
        self.assertEqual(payout.gross_amount, Decimal('30800.00'))
        self.assertEqual(payout.fee_amount, Decimal('3020.00'))
        self.assertEqual(payout.net_amount, Decimal('27780.00'))
        self.assertEqual(payout.payments_count, 2)
        payment.refresh_from_db()
        self.assertEqual((payment.settlement_status, payment.payout), ('settled', payout))

    def test_refuses_without_charter_fee_setting(self):
        self._charter('CHT-R10-6')
        with override_settings():
            from django.conf import settings
            del settings.PLATFORM_CHARTER_FEE_PERCENT
            with self.assertRaises(CommandError):
                self._settle()
