import io
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking, Payment
from bookings.tests.test_round5 import _Fixture
from bookings.tests.test_round12 import _url_name
from charters.models import CharterRequest
from companies.models import Company, Trip
from drivers.models import Driver
from users.phone import canonical_phone

User = get_user_model()
STRONG = 'Tr4velSafe-2026'


class _Bookings(_Fixture):
    def mk(self, status, ref, payment_status='pending', user=None):
        owner = self.passenger
        if user is not None:
            self.passenger = user
        try:
            booking, payment = self.booking(status, ref, payment_status=payment_status)
        finally:
            self.passenger = owner
        Booking.objects.filter(pk=booking.pk).update(seats=1)
        return booking, payment

    def create(self, user):
        self.client.force_authenticate(user=user)
        return self.client.post(
            reverse(f"bookings:{_url_name('create_booking')}"),
            {'trip_id': self.trip.id, 'seats': 1, 'pickup_location': 'CBD'},
            format='json',
        )


class PendingCapTests(_Bookings, APITestCase):
    def setUp(self):
        self.build('1301')

    @override_settings(MAX_PENDING_BOOKINGS_PER_USER=2)
    def test_user_cannot_exceed_the_pending_cap(self):
        for i in range(2):
            self.mk('pending', f'CAP-{i}')
        before = Booking.objects.count()
        response = self.create(self.passenger)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('unpaid', str(response.data))
        self.assertEqual(Booking.objects.count(), before)

    @override_settings(MAX_PENDING_BOOKINGS_PER_USER=2)
    def test_cap_is_per_user(self):
        for i in range(2):
            self.mk('pending', f'CAPU-{i}')
        other = User.objects.create_user(
            username='r13_other', password=STRONG, phone_number='+254733001301')
        response = self.create(other)
        self.assertEqual(response.status_code, 201, response.data)

    @override_settings(MAX_PENDING_BOOKINGS_PER_USER=2)
    def test_paid_bookings_do_not_count_towards_the_cap(self):
        for i in range(3):
            self.mk('confirmed', f'CAPC-{i}', payment_status='confirmed')
        response = self.create(self.passenger)
        self.assertEqual(response.status_code, 201, response.data)


class ExpirePendingBookingsTests(_Bookings, APITestCase):
    def setUp(self):
        self.build('1302')
        Trip.objects.filter(pk=self.trip.pk).update(capacity=1)
        self.old, _ = self.mk('pending', 'EXP-OLD')
        self._age(self.old, hours=2)
        self.buyer = User.objects.create_user(
            username='r13_buyer', password=STRONG, phone_number='+254733001302')

    def _age(self, booking, hours):
        Booking.objects.filter(pk=booking.pk).update(
            created_at=timezone.now() - timedelta(hours=hours))

    def _expire(self):
        out = io.StringIO()
        call_command('expire_pending_bookings', stdout=out)
        return out.getvalue()

    def test_abandoned_booking_frees_its_seat(self):
        self.assertEqual(self.create(self.buyer).status_code, 400)   # the trip looks full
        self.assertIn('cancelled 1', self._expire())
        self.old.refresh_from_db()
        self.assertEqual(self.old.status, 'cancelled')
        response = self.create(self.buyer)
        self.assertEqual(response.status_code, 201, response.data)

    def test_fresh_pending_booking_is_left_alone(self):
        fresh, _ = self.mk('pending', 'EXP-NEW')
        self._expire()
        fresh.refresh_from_db()
        self.assertEqual(fresh.status, 'pending')

    def test_confirmed_booking_is_left_alone(self):
        confirmed, _ = self.mk('confirmed', 'EXP-CONF', payment_status='confirmed')
        self._age(confirmed, hours=2)
        self._expire()
        confirmed.refresh_from_db()
        self.assertEqual(confirmed.status, 'confirmed')

    def test_pending_booking_with_a_confirmed_payment_is_left_alone(self):
        Payment.objects.filter(booking=self.old).update(status='confirmed')
        self._expire()
        self.old.refresh_from_db()
        self.assertEqual(self.old.status, 'pending')

    def test_trips_that_are_no_longer_scheduled_are_left_alone(self):
        Trip.objects.filter(pk=self.trip.pk).update(status='boarding')
        self._expire()
        self.old.refresh_from_db()
        self.assertEqual(self.old.status, 'pending')

    def test_second_run_cancels_nothing(self):
        self._expire()
        self.assertIn('cancelled 0', self._expire())


class CanonicalPhoneTests(TestCase):
    def test_kenyan_formats_converge(self):
        for raw in ('0712345678', '+254712345678', '254712345678', '712345678',
                    '+254 712 345 678', '0712-345-678', '+254 0712345678'):
            self.assertEqual(canonical_phone(raw), '+254712345678', raw)
        self.assertEqual(canonical_phone('0112345678'), '+254112345678')

    def test_unrecognised_numbers_are_never_corrupted(self):
        self.assertEqual(canonical_phone('+14155552671'), '+14155552671')
        self.assertEqual(canonical_phone('07123'), '07123')
        self.assertEqual(canonical_phone(''), '')
        self.assertIsNone(canonical_phone(None))

    def test_user_phone_is_stored_canonical(self):
        user = User.objects.create_user(
            username='r13_u1', password=STRONG, phone_number='0712 345 678')
        user.refresh_from_db()
        self.assertEqual(user.phone_number, '+254712345678')

    def test_driver_phone_is_stored_canonical(self):
        company = Company.objects.create(name='R13 Phone Co')
        driver = Driver.objects.create(
            company=company, name='D', phone_number='0712345679', bus_number='KAA 9')
        driver.refresh_from_db()
        self.assertEqual(driver.phone_number, '+254712345679')

    def test_foreign_number_survives_a_save(self):
        user = User.objects.create_user(
            username='r13_u2', password=STRONG, phone_number='+14155552671')
        user.refresh_from_db()
        self.assertEqual(user.phone_number, '+14155552671')


class NormalizePhonesTests(TestCase):
    def setUp(self):
        self.co = Company.objects.create(name='R13 Norm Co')
        self.driver = Driver.objects.create(
            company=self.co, name='D', phone_number='+254712000001', bus_number='KAA 1')
        self.driver_user = User.objects.create_user(
            username='r13_du', password=STRONG, phone_number='+254712000001',
            role='driver', company=self.co)
        # Simulate legacy raw rows: .update() bypasses the pre_save hook.
        Driver.objects.filter(pk=self.driver.pk).update(phone_number='0712000001')
        User.objects.filter(pk=self.driver_user.pk).update(phone_number='0712000001')

    def _run(self, **kwargs):
        out = io.StringIO()
        call_command('normalize_phones', stdout=out, **kwargs)
        return out.getvalue()

    def test_report_changes_nothing(self):
        output = self._run()
        self.assertIn('2 to change', output)
        self.assertEqual(Driver.objects.get(pk=self.driver.pk).phone_number, '0712000001')

    def test_apply_makes_driver_and_login_account_match(self):
        self._run(apply=True)
        driver = Driver.objects.get(pk=self.driver.pk)
        user = User.objects.get(pk=self.driver_user.pk)
        self.assertEqual(driver.phone_number, '+254712000001')
        self.assertEqual(user.phone_number, driver.phone_number)

    def test_collision_blocks_everything(self):
        User.objects.create_user(username='r13_c1', password=STRONG, phone_number='+254712000009')
        b = User.objects.create_user(username='r13_c2', password=STRONG, phone_number='+254733000009')
        User.objects.filter(pk=b.pk).update(phone_number='0712000009')
        with self.assertRaises(CommandError):
            self._run(apply=True)
        self.assertEqual(User.objects.get(pk=b.pk).phone_number, '0712000009')
        self.assertEqual(Driver.objects.get(pk=self.driver.pk).phone_number, '0712000001')

    def test_driver_sharing_a_number_with_a_passenger_blocks(self):
        User.objects.create_user(username='r13_p', password=STRONG, phone_number='+254712000010')
        other = Driver.objects.create(
            company=self.co, name='D2', phone_number='+254712000011', bus_number='KAA 2')
        Driver.objects.filter(pk=other.pk).update(phone_number='0712000010')
        output = self._run()
        self.assertIn('BLOCKER', output)
        with self.assertRaises(CommandError):
            self._run(apply=True)

    def test_unrecognised_numbers_are_reported_not_changed(self):
        user = User.objects.create_user(
            username='r13_f', password=STRONG, phone_number='+14155552671')
        output = self._run(apply=True)
        self.assertIn('UNRECOGNISED', output)
        self.assertEqual(User.objects.get(pk=user.pk).phone_number, '+14155552671')


class CharterAccessControlTests(_Fixture, APITestCase):
    """Nobody but the right people may read, price, pay for or complete a hire."""

    BASE = '/api/charters/'

    def setUp(self):
        self.build('1304')
        self.requested = self.charter('requested')
        self.quoted = self.charter('quoted', price=Decimal('30000.00'))
        self.confirmed = self.charter(
            'confirmed', ref='CHT-ACL-1', price=Decimal('30000.00'), depart_days=-1)
        self.intruder = User.objects.create_user(
            username='r13_ci', password=STRONG, phone_number='+254744001304')

    def charter(self, status, ref=None, price=None, depart_days=5):
        return CharterRequest.objects.create(
            passenger=self.passenger, company=self.company, driver=self.driver,
            purpose='Wedding', pickup_location='CBD', destination='Nakuru',
            depart_at=timezone.now() + timedelta(days=depart_days), passenger_count=14,
            contact_name='Test', contact_phone='+254700000000',
            status=status, quote_price=price, provider_reference=ref,
            quote_valid_until=(timezone.now() + timedelta(days=2)) if status == 'quoted' else None,
        )

    def _snapshot(self):
        return [
            (c.status, c.quote_price, c.provider_reference)
            for c in CharterRequest.objects.order_by('pk')
        ]

    def _call(self, method, path, body=None):
        with patch('connect.paystack_extra.requests.post') as post, \
                patch('connect.paystack_extra.requests.get') as get:
            if method == 'get':
                response = self.client.get(f'{self.BASE}{path}')
            else:
                response = self.client.post(f'{self.BASE}{path}', body or {}, format='json')
        post.assert_not_called()
        get.assert_not_called()
        return response

    def test_another_passenger_cannot_touch_the_hire(self):
        before = self._snapshot()
        self.client.force_authenticate(user=self.intruder)
        for method, path in (
            ('get', f'{self.quoted.id}/'),
            ('post', f'{self.quoted.id}/cancel/'),
            ('post', f'{self.quoted.id}/pay/'),
            ('post', f'{self.quoted.id}/verify/'),
            ('post', f'{self.confirmed.id}/complete/'),
        ):
            self.assertGreaterEqual(self._call(method, path).status_code, 400, path)
        self.assertEqual(self._snapshot(), before)

    def test_the_customer_cannot_price_their_own_hire(self):
        before = self._snapshot()
        self.client.force_authenticate(user=self.passenger)
        body = {
            'quote_price': '1.00', 'price': '1.00', 'amount': '1.00',
            'quote_valid_until': (timezone.now() + timedelta(days=1)).isoformat(),
        }
        self._call('post', f'{self.requested.id}/quote/', body)
        self._call('post', f'{self.quoted.id}/quote/', body)
        self.assertEqual(self._snapshot(), before)

    def test_the_customer_cannot_complete_their_own_hire(self):
        before = self._snapshot()
        self.client.force_authenticate(user=self.passenger)
        self._call('post', f'{self.confirmed.id}/complete/')
        self.assertEqual(self._snapshot(), before)

    def test_staff_of_another_company_cannot_quote_or_decline(self):
        before = self._snapshot()
        other = Company.objects.create(name='R13 Other Co')
        manager = User.objects.create_user(
            username='r13_other_mgr', password=STRONG, phone_number='+254733001305',
            role='company_manager', company=other)
        self.client.force_authenticate(user=manager)
        body = {
            'quote_price': '1.00',
            'quote_valid_until': (timezone.now() + timedelta(days=1)).isoformat(),
        }
        self._call('post', f'{self.requested.id}/quote/', body)
        self._call('post', f'{self.requested.id}/decline/', {'reason': 'no'})
        self.assertEqual(self._snapshot(), before)

    def test_anonymous_users_are_rejected(self):
        before = self._snapshot()
        for method, path in (
            ('get', f'{self.quoted.id}/'),
            ('post', f'{self.quoted.id}/cancel/'),
            ('post', f'{self.quoted.id}/pay/'),
            ('post', f'{self.quoted.id}/verify/'),
            ('post', f'{self.confirmed.id}/complete/'),
        ):
            self.assertIn(self._call(method, path).status_code, (401, 403), path)
        self.assertEqual(self._snapshot(), before)
