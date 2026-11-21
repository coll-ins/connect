"""Hostile but well-signed webhook bodies, odd numerals and wrong types answer 4xx/200, never 500."""
import datetime as dt
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from bookings.models import Booking, Incident
from bookings.tests.review_base import WorldMixin
from bookings.tests.sim import fake_gateway as fg

BOOKING_HOOK = '/api/bookings/webhooks/paystack/'
REFUND_HOOK = '/api/bookings/webhooks/paystack/refund/'


class SignedBodyTests(WorldMixin, TestCase):
    def post(self, path, body):
        return Client(raise_request_exception=False).generic(
            'POST', path, body, content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=fg.sign(body))

    def test_a_signed_body_that_is_not_a_json_object_is_400(self):
        for body in (b'[]', b'null', b'"x"', b'1', b'\xff\xfe{}', b'{', b''):
            for path in (BOOKING_HOOK, REFUND_HOOK):
                self.assertEqual(self.post(path, body).status_code, 400, (body, path))

    def test_a_null_or_non_object_data_member_is_400(self):
        for event, path in (('charge.success', BOOKING_HOOK), ('refund.failed', REFUND_HOOK),
                            ('refund.failed', BOOKING_HOOK)):
            for data in ('null', '[]', '"x"', '5'):
                body = ('{"event": "%s", "data": %s}' % (event, data)).encode()
                self.assertEqual(self.post(path, body).status_code, 400, (body, path))

    def test_a_non_text_reference_is_400(self):
        for ref in ('5', '["a"]', '{}', 'true'):
            body = ('{"event": "charge.success", "data": {"reference": %s}}' % ref).encode()
            self.assertEqual(self.post(BOOKING_HOOK, body).status_code, 400, body)
            body = ('{"event": "refund.failed", "data": {"transaction_reference": %s}}' % ref).encode()
            self.assertEqual(self.post(REFUND_HOOK, body).status_code, 400, body)

    def test_an_absurd_amount_never_crashes_a_charge_or_refund_event(self):
        for amount in ('1e30', '1e999', '-1e999', '"x"', '[]', '{}', 'null', 'true'):
            body = ('{"event": "charge.success", "data": {"reference": "CONNECT-1-nope", '
                    '"amount": %s, "currency": "KES"}}' % amount).encode()
            self.assertIn(self.post(BOOKING_HOOK, body).status_code, (200, 400), body)
            body = ('{"event": "refund.failed", "data": {"transaction_reference": "CONNECT-1-nope", '
                    '"amount": %s}}' % amount).encode()
            self.assertIn(self.post(REFUND_HOOK, body).status_code, (200, 400), body)

    def test_a_transfer_event_with_an_overflowing_amount_is_answered(self):
        from wallets.webhook import handle_event
        for amount in (1e30, float('inf'), 'x'):
            self.assertTrue(handle_event({'event': 'transfer.failed', 'data': {
                'reference': 'wd-unknown', 'amount': amount}}))
        body = b'{"event": "transfer.failed", "data": {"reference": "wd-x", "amount": 1e999}}'
        self.assertEqual(self.post(BOOKING_HOOK, body).status_code, 200)


class IncidentTypeTests(WorldMixin, TestCase):
    def test_a_non_text_incident_type_is_400_and_creates_nothing(self):
        for bad in ([], {}, ['breakdown'], 5, True, None):
            r = self.api(self.mgr).post('/api/bookings/incidents/report/', {
                'trip_id': self.trip1.id, 'incident_type': bad, 'description': 'x'}, format='json')
            self.assertEqual(r.status_code, 400, (bad, r.content[:120]))
        self.assertEqual(Incident.objects.count(), 0)


class WalkInInputTests(WorldMixin, TestCase):
    def walk_in(self, **body):
        body.setdefault('seats', 1)
        return self.api(self.op_all).post(
            f'/api/bookings/walk-in/{self.trip1.id}/', body, format='json')

    def test_a_phone_that_is_not_a_kenyan_mobile_is_400_and_creates_no_account(self):
        before = User_count()
        for bad in ('NaN', 'Infinity', None, True, [], {}, '1e5', '-0', '0x10', '5', 10 ** 30,
                    '٠٧١١٢٣٤٥٦٧٨', '0711', '+1 202 555 0100', ''):
            self.assertEqual(self.walk_in(phone_number=bad).status_code, 400, repr(bad))
        self.assertEqual(User_count(), before)

    def test_a_valid_phone_in_any_spelling_is_booked_under_the_canonical_number(self):
        for spelling in ('0711555001', '+254711555002', '254711555003', '0711 555 004'):
            self.assertEqual(self.walk_in(phone_number=spelling).status_code, 201, spelling)
        from bookings.tests.review_base import User
        self.assertTrue(User.objects.filter(phone_number='+254711555004').exists())

    def test_non_ascii_or_non_integer_seats_are_400(self):
        for bad in ('٥', '٠١', True, 1.5, 'x', None, [], '1e1'):
            self.assertEqual(
                self.walk_in(phone_number='0711555009', seats=bad).status_code, 400, repr(bad))

    def test_more_than_six_seats_is_400_seat_limit(self):
        r = self.walk_in(phone_number='0711555010', seats=7)
        self.assertEqual((r.status_code, r.json()['code']), (400, 'seat_limit'))
        self.assertEqual(self.walk_in(phone_number='0711555010', seats=6).status_code, 201)


def User_count():
    from bookings.tests.review_base import User
    return User.objects.count()


class SeatLimitTests(WorldMixin, TestCase):
    def book(self, user, seats, trip=None, **extra):
        trip = trip or self.trip1
        trip.status = 'scheduled'
        trip.capacity = 40
        trip.departure_at = timezone.now() + dt.timedelta(hours=5)
        trip.save()
        return self.api(user).post('/api/bookings/create/', {
            'trip_id': trip.id, 'seats': seats, 'pickup_stage_id': self.s1.id, **extra}, format='json')

    def test_seven_seats_in_one_booking_is_400_seat_limit(self):
        r = self.book(self.pax, 7)
        self.assertEqual((r.status_code, r.json()['code']), (400, 'seat_limit'))
        self.assertEqual(Booking.objects.filter(user=self.pax).count(), 0)

    def test_six_seats_in_one_booking_is_allowed(self):
        self.assertEqual(self.book(self.pax, 6).status_code, 201)

    def test_unpaid_seats_on_one_trip_stop_at_six(self):
        self.assertEqual(self.book(self.pax, 4).status_code, 201)
        r = self.book(self.pax, 3)
        self.assertEqual((r.status_code, r.json()['code']), (400, 'seat_limit'))
        self.assertEqual(self.book(self.pax, 2).status_code, 201)
        r = self.book(self.pax, 1)
        self.assertEqual((r.status_code, r.json()['code']), (400, 'seat_limit'))

    def test_the_limit_is_per_user_not_per_trip_overall(self):
        self.assertEqual(self.book(self.pax, 6).status_code, 201)
        self.assertEqual(self.book(self.pax2, 6).status_code, 201)

    def test_an_expired_hold_or_a_paid_booking_no_longer_counts(self):
        first = self.book(self.pax, 6).json()['booking_id']
        Booking.objects.filter(pk=first).update(held_until=timezone.now() - dt.timedelta(minutes=1))
        self.assertEqual(self.book(self.pax, 6).status_code, 201)
        Booking.objects.filter(user=self.pax, status='pending').update(status='confirmed')
        self.assertEqual(self.book(self.pax, 6).status_code, 201)

    def test_non_ascii_digits_in_seats_are_400(self):
        self.assertEqual(self.book(self.pax, '٥').status_code, 400)

    def test_a_route_priced_before_the_ceiling_cannot_make_a_booking_crash(self):
        self.r1.price = Decimal('99999999.99')
        self.r1.save()
        r = self.book(self.pax, 6)
        self.assertEqual(r.status_code, 400, r.content[:160])
        self.assertEqual(Booking.objects.filter(user=self.pax).count(), 0)
