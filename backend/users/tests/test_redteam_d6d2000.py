from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from bookings.models import Booking
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver
from users.identity import is_driver_account_for


class PhoneVariantTests(TestCase):
    def setUp(self):
        self.a = Company.objects.create(name='A')
        self.b = Company.objects.create(name='B')
        self.login = get_user_model().objects.create_user(
            username='old', password='password123', phone_number='+254711000111', role='driver')

    def test_legit_driver_with_spaced_phone_row_is_not_locked_out(self):
        d = Driver.objects.create(name='A', phone_number='+254 711 000 111', bus_number='K1', company=self.a)
        self.assertTrue(is_driver_account_for(self.login, d))

    def test_rival_row_with_spaced_phone_is_not_actable(self):
        Driver.objects.create(name='A', phone_number='+254711000111', bus_number='K1', company=self.a)
        rival = Driver.objects.create(name='B', phone_number='0711 000 111', bus_number='K2', company=self.b)
        self.assertFalse(is_driver_account_for(self.login, rival))


class StuckLaterStageTests(TestCase):
    def test_later_stage_confirmed_booking_on_abandoned_trip_is_eventually_settled(self):
        c = Company.objects.create(name='C')
        r = Route.objects.create(company=c, name='R', start_point='a', end_point='b', price=Decimal('800'))
        PickupStage.objects.create(route=r, name='s1', order=1, latitude=0, longitude=0)
        s2 = PickupStage.objects.create(route=r, name='s2', order=2, latitude=0, longitude=0)
        d = Driver.objects.create(company=c, name='D', phone_number='0700000099', bus_number='K9')
        u = get_user_model().objects.create_user(username='p', password='password123', phone_number='+254700000098')
        t = Trip.objects.create(route=r, driver=d, capacity=14, status='departed',
                                departure_at=timezone.now() - timedelta(days=3))
        b = Booking.objects.create(user=u, route=r, driver=d, trip=t, pickup_stage=s2,
                                   pickup_location='s2', total_amount=Decimal('800'), status='confirmed')
        for _ in range(2):
            call_command('process_noshows', stdout=StringIO(), stderr=StringIO())
            call_command('close_stale_trips', stdout=StringIO())
        b.refresh_from_db()
        self.assertIn(b.status, ('no_show', 'completed', 'cancelled'))
