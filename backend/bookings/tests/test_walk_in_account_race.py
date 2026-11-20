"""Walk-in account creation: concurrent first sightings of a phone, and no takeover path."""
import datetime as dt
import unittest

from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking
from bookings.tests.review_base import PG, User, WorldMixin, run_together
from companies.models import Trip


@unittest.skipUnless(PG, 'needs real row locks')
class WalkInRaceTests(WorldMixin, TransactionTestCase):
    def test_same_new_phone_walked_in_on_two_trips_at_once_does_not_500(self):
        t2 = Trip.objects.create(route=self.r1, driver=self.drv2, capacity=14, status='boarding',
                                 departure_at=timezone.now() + dt.timedelta(minutes=40))
        for i in range(4):
            phone = f'07551110{i}0'

            def w(t):
                return lambda: self.api(self.op_all).post(
                    f'/api/bookings/walk-in/{t.id}/', {'seats': 1, 'phone_number': phone}, format='json').status_code
            out, errs = run_together([w(self.trip1), w(t2)])
            self.assertEqual(errs, [], errs)
            self.assertEqual(out, [201, 201])
            canonical = '+254' + phone[1:]
            self.assertEqual(User.objects.filter(phone_number=canonical).count(), 1)
            self.assertEqual(Booking.objects.filter(user__phone_number=canonical).count(), 2)


class WalkInAccountTests(WorldMixin, TestCase):
    def walk_in(self, phone='0755000333'):
        return self.api(self.op_all).post(
            f'/api/bookings/walk-in/{self.trip1.id}/', {'seats': 1, 'phone_number': phone}, format='json')

    def test_walk_in_account_has_an_unusable_password(self):
        self.assertEqual(self.walk_in().status_code, 201)
        user = User.objects.get(phone_number='+254755000333')
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.role, 'passenger')

    def test_nobody_can_log_in_to_a_walk_in_account_with_a_guessed_password(self):
        self.walk_in()
        for guess in ('None', '!', 'password', 'walkin_254755000333'):
            r = APIClient().post('/api/users/login/', {'phone_number': '0755000333', 'password': guess},
                                 format='json')
            self.assertEqual(r.status_code, 401, guess)

    def test_staff_phone_is_refused_for_a_walk_in(self):
        r = self.walk_in('0722000001')
        self.assertEqual(r.status_code, 400, r.content[:200])
