"""World simulation, part 4: many SACCOs with live data, and who can see what."""
from unittest import mock

from django.db import transaction
from django.urls import reverse

from bookings.models import Booking

from .base import SimCase
from .invariants import isolation_problems


class WorldIsolationTests(SimCase):
    def _populate(self):
        out = []
        for ci, company in enumerate(self.companies()):
            for ri, route in enumerate(self.routes_of(company)[:2]):
                self.add_stages(route, index=ci * 2 + ri) if not route.pickup_stages.exists() else None
                trip = self.trip(route, minutes=120)
                for _ in range(2):
                    user = self.user()
                    booking, _ref = self.confirmed_booking(user, trip)
                    out.append(booking)
                self.booking(self.user(), trip)             # one unpaid
        return out

    def test_staff_of_one_sacco_see_nothing_of_another_in_a_populated_world(self):
        bookings = self._populate()
        self.assertEqual(isolation_problems(self), [])
        self.assertEqual(len(bookings), 12)

    def test_an_operator_limited_to_one_route_cannot_touch_its_siblings(self):
        company = self.companies()[0]
        r1, r2 = self.routes_of(company)[:2]
        for i, route in enumerate((r1, r2)):
            self.add_stages(route, index=i)
        t1, t2 = self.trip(r1, minutes=120), self.trip(r2, minutes=120)
        b1, _ = self.confirmed_booking(self.user(), t1)
        b2, _ = self.confirmed_booking(self.user(), t2)
        op = self.staff(company, 'company_operator')
        op.all_routes = False
        op.save(update_fields=['all_routes'])
        op.assigned_routes.set([r1])
        client = self.api(op)
        self.assertEqual(client.get(reverse('bookings:get-booking-detail', args=[b1.pk])).status_code, 200)
        for name in ('bookings:get-booking-detail', 'bookings:booking-live-location'):
            self.assertIn(client.get(reverse(name, args=[b2.pk])).status_code, (403, 404))
        self.assertIn(client.get(reverse('trip-seat-summary', args=[t2.pk])).status_code, (403, 404))
        self.assertNotIn(b2.booking_number, client.get(reverse('bookings:get-all-bookings')).content.decode())
        self.assertEqual(client.post(reverse('bookings:cancel-booking', args=[b2.pk]), {}, format='json').status_code in (403, 404), True)
        self.assertEqual(Booking.objects.get(pk=b2.pk).status, 'confirmed')


class AlertsInsideTransactionsTests(SimCase):
    # Finding SIM-1: services.cancel_trip_bookings sends the admin SMS inside the caller's
    # transaction (trip and booking row locks held during an external call). Routed to the
    # owner of bookings/services.py; fixed by sending the alert on commit.
    def test_no_admin_sms_is_sent_while_a_transaction_is_open(self):
        """Probe: a gateway-class call (here the SMS alert) must not run inside atomic()."""
        company = self.companies()[0]
        route = self.routes_of(company)[0]
        self.add_stages(route)
        trip = self.trip(route, minutes=120)
        user = self.user()
        booking, _ = self.confirmed_booking(user, trip)
        # A paid digital booking whose refund cannot be reserved: the admin alert fires inside cancel_trip_bookings.
        from bookings.models import Payment
        Payment.objects.filter(booking=booking).update(provider_reference=None)
        r = self.api(self.staff(company, 'company_manager')).post(
            reverse('update_trip_status', args=[trip.pk]), {'status': 'cancelled'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(self.alerts('could not be refunded'))
        inside = [m for m, _, label, atomic in self.fake.sms if atomic]
        self.assertEqual(inside, [])

    def _unrefundable_booking(self):
        from bookings.models import Payment
        company = self.companies()[0]
        route = self.routes_of(company)[0]
        self.add_stages(route)
        trip = self.trip(route, minutes=120)
        booking, _ = self.confirmed_booking(self.user(), trip)
        Payment.objects.filter(booking=booking).update(provider_reference=None)
        return trip

    def test_alert_is_sent_exactly_once_after_commit(self):
        from bookings import services
        trip = self._unrefundable_booking()
        with mock.patch.object(services, '_alert_admin') as alert:
            with transaction.atomic():
                services.cancel_trip_bookings(trip, [])
                alert.assert_not_called()
        self.assertEqual(alert.call_count, 1)

    def test_alert_is_dropped_when_the_transaction_rolls_back(self):
        from bookings import services
        trip = self._unrefundable_booking()
        with mock.patch.object(services, '_alert_admin') as alert:
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    services.cancel_trip_bookings(trip, [])
                    raise RuntimeError('boom')
        alert.assert_not_called()
