"""A wallet payment gets the same arrival tolerance as card and cash: late by a few seconds is fine unless the seat is gone.

Sim cases restore the serialized database, so they stay in the sim package, which runs before any plain transaction test.
"""
from decimal import Decimal

from django.urls import reverse

from bookings.models import Booking
from companies.models import Trip

from bookings.tests.sim import test_world_wallet as ww


class WalletPayToleranceTests(ww.WalletCase):
    def pay(self, user, booking):
        return self.api(user).post(reverse('bookings:pay-from-wallet', args=[booking.pk]), {}, format='json')

    def test_a_hold_that_ran_out_seconds_ago_still_pays_when_the_seat_is_free(self):
        user = self.user()
        self.fund(user, 500)
        booking = self.booking(user, self.trip_)
        self.expire_hold(booking, seconds_ago=30)
        r = self.pay(user, booking)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'confirmed')
        self.assertEqual(self.balance(user), Decimal('500') - self.fare)
        self.assertEqual(self.fake.leaks, [])

    def test_a_hold_that_ran_out_past_the_tolerance_is_refused_with_no_debit(self):
        user = self.user()
        self.fund(user, 500)
        booking = self.booking(user, self.trip_)
        self.expire_hold(booking, seconds_ago=61)
        r = self.pay(user, booking)
        self.assertEqual((r.status_code, r.json()['code']), (409, 'hold_expired'))
        self.assertEqual(self.balance(user), Decimal('500'))
        self.assertEqual(self.fake.leaks, [])

    def test_inside_the_tolerance_but_the_seat_was_resold_is_refused_with_no_debit(self):
        Trip.objects.filter(pk=self.trip_.pk).update(capacity=1)
        user, rival = self.user(), self.user()
        self.fund(user, 500)
        booking = self.booking(user, self.trip_)
        self.expire_hold(booking, seconds_ago=30)
        self.booking(rival, self.trip_)                     # takes the seat the lapsed hold no longer protects
        r = self.pay(user, booking)
        self.assertEqual((r.status_code, r.json()['code']), (409, 'hold_expired'))
        self.assertEqual(self.balance(user), Decimal('500'))
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'pending')
        self.assertEqual(self.fake.leaks, [])
