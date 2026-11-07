"""Real concurrency: several passengers hit the last seat at the same instant.

Runs only on PostgreSQL (CI and production): SQLite serialises every write,
so it cannot prove anything about row locks.
"""
import datetime as dt
import threading
import unittest
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import Sum
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()


@unittest.skipUnless(connection.vendor == 'postgresql', 'needs real row locks')
class LastSeatRaceTests(TransactionTestCase):
    def setUp(self):
        company = Company.objects.create(name='Race Co', areas_served='Nairobi')
        self.route = Route.objects.create(
            company=company, name='CBD - Ngong', start_point='CBD',
            end_point='Ngong', price=Decimal('100'))
        self.stage = PickupStage.objects.create(
            route=self.route, name='Kencom', order=1,
            latitude=Decimal('-1.2856'), longitude=Decimal('36.8250'))
        driver = Driver.objects.create(
            name='D', phone_number='+254711000000', bus_number='KDA 001A',
            company=company)
        self.trip = Trip.objects.create(
            route=self.route, driver=driver, capacity=14, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=2))

    def _fill(self, seats):
        filler = User.objects.create_user(
            username='filler', password='pw-123456', phone_number='+254711999999')
        Booking.objects.create(
            user=filler, trip=self.trip, route=self.route, driver=self.trip.driver,
            seats=seats, total_amount=Decimal('100') * seats, status='confirmed',
            pickup_location='Kencom')

    def _race(self, racers, seats_each):
        users = [
            User.objects.create_user(
                username=f'racer{i}', password='pw-123456',
                phone_number=f'+2547120000{i:02d}')
            for i in range(racers)
        ]
        barrier = threading.Barrier(racers)
        codes = []

        def book(user):
            client = APIClient()
            client.force_authenticate(user)
            barrier.wait()
            try:
                r = client.post('/api/bookings/create/', {
                    'trip_id': self.trip.id, 'seats': seats_each,
                    'pickup_stage_id': self.stage.id}, format='json')
                codes.append(r.status_code)
            finally:
                connection.close()

        threads = [threading.Thread(target=book, args=(u,)) for u in users]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        taken = (self.trip.bookings.exclude(status='cancelled')
                 .aggregate(s=Sum('seats'))['s'])
        return codes, taken

    def test_ten_passengers_one_last_seat(self):
        self._fill(13)
        codes, taken = self._race(10, 1)
        self.assertEqual(codes.count(201), 1, codes)
        self.assertEqual(taken, 14)

    def test_two_people_ask_for_two_of_the_last_two_seats(self):
        self._fill(12)
        codes, taken = self._race(2, 2)
        self.assertEqual(codes.count(201), 1, codes)
        self.assertEqual(taken, 14)
