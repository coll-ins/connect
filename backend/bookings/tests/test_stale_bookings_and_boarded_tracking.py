from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import BoardingEvent, Booking
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()


class StaleBookingTestBase(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name='A', description='d', areas_served='N')
        self.route = Route.objects.create(
            company=self.company, name='R', start_point='CBD', end_point='Ngong',
            price=Decimal('100.00'),
        )
        self.stage = PickupStage.objects.create(
            route=self.route, name='S1', latitude=Decimal('-1.285'),
            longitude=Decimal('36.82'), order=1,
        )
        self.driver = Driver.objects.create(
            name='D', phone_number='0700000001', bus_number='K1', company=self.company,
        )
        self.user = User.objects.create_user(
            username='own', password='x', phone_number='0711000001',
        )
        self.client.force_authenticate(user=self.user)

    def trip(self, status, minutes_from_now):
        return Trip.objects.create(
            route=self.route, driver=self.driver, capacity=10, status=status,
            departure_at=timezone.now() + timedelta(minutes=minutes_from_now),
        )

    def booking(self, trip, status='pending'):
        return Booking.objects.create(
            user=self.user, route=self.route, trip=trip, driver=self.driver,
            pickup_stage=self.stage, pickup_location='S1', seats=1,
            total_amount=Decimal('100.00'), status=status,
        )


class DeadPendingBookingTests(StaleBookingTestBase):
    def status_after_my_bookings(self, booking):
        self.assertEqual(self.client.get('/api/bookings/my/').status_code, 200)
        booking.refresh_from_db()
        return booking.status

    def test_unpaid_booking_is_cancelled_once_departure_time_passes(self):
        booking = self.booking(self.trip('scheduled', -1))
        self.assertEqual(self.status_after_my_bookings(booking), 'cancelled')

    def test_three_week_old_unpaid_booking_on_a_finished_trip_is_cancelled(self):
        for status in ('departed', 'completed', 'cancelled'):
            booking = self.booking(self.trip(status, -21 * 24 * 60))
            self.assertEqual(self.status_after_my_bookings(booking), 'cancelled')

    def test_unpaid_booking_on_an_upcoming_trip_stays(self):
        booking = self.booking(self.trip('scheduled', 60))
        self.assertEqual(self.status_after_my_bookings(booking), 'pending')

    def test_unpaid_booking_can_still_pay_while_a_late_bus_is_boarding(self):
        booking = self.booking(self.trip('boarding', -30))
        self.assertEqual(self.status_after_my_bookings(booking), 'pending')

    def test_scheduled_job_also_cleans_up_a_departed_trip(self):
        booking = self.booking(self.trip('departed', -60))
        call_command('expire_pending_bookings', verbosity=0)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')

    def test_other_passengers_bookings_are_left_alone_by_my_bookings(self):
        other = User.objects.create_user(
            username='oth', password='x', phone_number='0711000002',
        )
        booking = self.booking(self.trip('departed', -60))
        Booking.objects.filter(pk=booking.pk).update(user=other)
        self.assertEqual(self.status_after_my_bookings(booking), 'pending')


class BoardedPassengerTrackingTests(StaleBookingTestBase):
    def boarded_booking(self, trip):
        booking = self.booking(trip, status='completed')
        BoardingEvent.objects.create(booking=booking, trip=trip, method='pin')
        return booking

    def test_passenger_keeps_the_live_map_after_boarding(self):
        booking = self.boarded_booking(self.trip('departed', -5))
        resp = self.client.get(f'/api/bookings/{booking.id}/live-location/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIs(resp.json()['boarded'], True)

    def test_my_bookings_says_who_has_boarded(self):
        self.boarded_booking(self.trip('departed', -5))
        self.assertIs(self.client.get('/api/bookings/my/').json()[0]['boarded'], True)

    def test_live_map_ends_when_the_trip_ends(self):
        booking = self.boarded_booking(self.trip('completed', -5))
        resp = self.client.get(f'/api/bookings/{booking.id}/live-location/')
        self.assertEqual(resp.status_code, 409)

    def test_completed_without_boarding_cannot_track(self):
        booking = self.booking(self.trip('departed', -5), status='completed')
        resp = self.client.get(f'/api/bookings/{booking.id}/live-location/')
        self.assertEqual(resp.status_code, 409)


class CompletingTripSettlesBookingsTests(StaleBookingTestBase):
    def test_marking_a_trip_completed_cancels_unpaid_bookings(self):
        admin = User.objects.create_superuser(
            username='root', password='x', phone_number='0711000009', email='a@example.test',
        )
        self.client.force_authenticate(user=admin)
        trip = self.trip('departed', -60)
        booking = self.booking(trip)

        resp = self.client.post(
            f'/api/companies/trips/{trip.id}/status/', {'status': 'completed'}, format='json',
        )

        self.assertEqual(resp.status_code, 200, resp.content)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
