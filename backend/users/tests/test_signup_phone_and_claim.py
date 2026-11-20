"""Signup: one canonical phone, no 500 on spelling clashes, and a walk-in account can be claimed."""
import unittest

from django.core.cache import cache
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from bookings.models import Booking
from bookings.tests.review_base import PG, User, WorldMixin

GOOD = {'password': 'Zx9-longer-pass', 'name': 'Alice Wanjiru'}


def signup(phone, client=None, **extra):
    cache.clear()  # the per-phone signup throttle is not what these tests are about
    return (client or APIClient()).post(
        '/api/users/signup/', {'phone_number': phone, **GOOD, **extra}, format='json')


class SignupPhoneTests(TestCase):
    def setUp(self):
        User.objects.create_user(username='existing', password='pw-123456', phone_number='+254712345678')

    def test_every_spelling_of_a_taken_phone_gets_the_same_400_body(self):
        bodies = set()
        for phone in ('+254712345678', '0712345678', '254712345678', '+2540712345678',
                      '254 0712345678', '0712 345 678'):
            r = signup(phone)
            self.assertEqual(r.status_code, 400, (phone, r.content[:120]))
            bodies.add(r.content)
        self.assertEqual(len(bodies), 1)
        self.assertEqual(User.objects.filter(phone_number__endswith='712345678').count(), 1)

    def test_a_legacy_row_stored_as_07_is_also_taken(self):
        User.objects.create_user(username='legacy', password='pw-123456', phone_number='0733000111')
        r = signup('+254733000111')
        self.assertEqual(r.status_code, 400, r.content[:120])

    def test_a_new_phone_is_stored_in_canonical_form(self):
        r = signup('+2540799000111')
        self.assertEqual(r.status_code, 201, r.content[:160])
        self.assertEqual(r.json()['user']['phone'], '+254799000111')

    def test_a_non_text_or_non_ascii_phone_is_400(self):
        for bad in (None, 712345678, ['0712345678'], {}, True, '٠٧١٢٣٤٥٦٧٩'):
            self.assertEqual(signup(bad).status_code, 400, repr(bad))

    @override_settings(ALLOW_ADMIN_SIGNUP=True, ADMIN_SIGNUP_CODE='code-0123456789-abcdef-xyz')
    def test_admin_signup_with_a_spelling_clash_is_400_with_the_same_body(self):
        taken = signup('0712345678')
        for phone in ('+2540712345678', '0712345678'):
            r = APIClient().post('/api/users/admin-signup/', {
                'phone_number': phone, 'admin_code': 'code-0123456789-abcdef-xyz', **GOOD}, format='json')
            self.assertEqual(r.status_code, 400, (phone, r.content[:120]))
            self.assertEqual(r.content, taken.content)


class WalkInClaimTests(WorldMixin, TestCase):
    PHONE = '0755000333'

    def walk_in(self):
        r = self.api(self.op_all).post(
            f'/api/bookings/walk-in/{self.trip1.id}/', {'seats': 1, 'phone_number': self.PHONE}, format='json')
        self.assertEqual(r.status_code, 201, r.content[:160])
        return User.objects.get(phone_number='+254755000333')

    def test_signup_claims_the_walk_in_account_and_keeps_its_history(self):
        walked = self.walk_in()
        booking = Booking.objects.get(user=walked)
        r = signup(self.PHONE)
        self.assertEqual(r.status_code, 201, r.content[:160])
        self.assertEqual(r.json()['user']['id'], walked.id)
        self.assertEqual(User.objects.filter(phone_number='+254755000333').count(), 1)
        walked.refresh_from_db()
        self.assertTrue(walked.has_usable_password())
        self.assertTrue(walked.check_password('Zx9-longer-pass'))
        self.assertEqual((walked.first_name, walked.last_name), ('Alice', 'Wanjiru'))
        self.assertEqual(walked.role, 'passenger')
        self.assertTrue(Booking.objects.filter(pk=booking.pk, user=walked).exists())

    def test_the_claimed_account_can_log_in_and_sees_its_history(self):
        walked = self.walk_in()
        booking = Booking.objects.get(user=walked)
        signup(self.PHONE)
        client = APIClient()
        r = client.post('/api/users/login/', {'phone_number': self.PHONE, 'password': GOOD['password']}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:160])
        mine = client.get('/api/bookings/my/')
        self.assertEqual(mine.status_code, 200)
        self.assertEqual([b['booking_id'] for b in mine.json()], [booking.id])

    def test_a_weak_password_does_not_claim_the_account(self):
        walked = self.walk_in()
        r = signup(self.PHONE, password='12345678')
        self.assertEqual(r.status_code, 400, r.content[:160])
        walked.refresh_from_db()
        self.assertFalse(walked.has_usable_password())

    def test_a_claimed_account_cannot_be_claimed_again(self):
        self.walk_in()
        self.assertEqual(signup(self.PHONE).status_code, 201)
        before = User.objects.get(phone_number='+254755000333').password
        r = signup(self.PHONE, password='Another-pass-77')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(User.objects.get(phone_number='+254755000333').password, before)

    def test_a_real_account_cannot_be_claimed(self):
        real = User.objects.create_user(username='real', password='pw-123456', phone_number='+254755000444')
        before = real.password
        r = signup('0755000444', password='attacker-pass-1')
        self.assertEqual(r.status_code, 400)
        real.refresh_from_db()
        self.assertEqual(real.password, before)

    def test_staff_and_driver_accounts_without_a_password_cannot_be_claimed(self):
        staff = User.objects.create_user(
            username='nopw', password=None, phone_number='+254755000555',
            role='company_operator', company=self.co)
        self.assertEqual(signup('0755000555').status_code, 400)
        staff.refresh_from_db()
        self.assertFalse(staff.has_usable_password())

    def test_an_inactive_walk_in_account_cannot_be_claimed(self):
        walked = self.walk_in()
        User.objects.filter(pk=walked.pk).update(is_active=False)
        r = signup(self.PHONE)
        self.assertEqual(r.status_code, 400, r.content[:160])
        walked.refresh_from_db()
        self.assertFalse(walked.has_usable_password())

    def test_the_refusal_body_matches_the_one_for_a_real_account(self):
        self.walk_in()
        self.assertEqual(signup(self.PHONE).status_code, 201)
        claimed_again = signup(self.PHONE)
        User.objects.create_user(username='real2', password='pw-123456', phone_number='+254755000666')
        self.assertEqual(claimed_again.content, signup('0755000666').content)


@unittest.skipUnless(PG, 'needs real row locks')
class WalkInClaimRaceTests(WorldMixin, TransactionTestCase):
    def test_two_simultaneous_claims_make_one_winner(self):
        self.api(self.op_all).post(
            f'/api/bookings/walk-in/{self.trip1.id}/', {'seats': 1, 'phone_number': '0755000777'}, format='json')
        from bookings.tests.review_base import run_together
        out, errs = run_together([
            lambda: signup('0755000777', password='First-pass-9911').status_code,
            lambda: signup('0755000777', password='Second-pass-9922').status_code,
        ])
        self.assertEqual(errs, [], errs)
        self.assertEqual(sorted(out), [201, 400])
