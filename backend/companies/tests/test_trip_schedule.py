from datetime import datetime, time
from io import StringIO
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase

from companies.models import Company, Route, Trip, TripSchedule
from drivers.models import Driver

NBO = ZoneInfo('Africa/Nairobi')
TUE_6AM = datetime(2030, 1, 1, 6, 0, tzinfo=NBO)   # Tuesday
TUE_8AM = datetime(2030, 1, 1, 8, 0, tzinfo=NBO)
NOW = 'django.utils.timezone.now'


def run(now):
    with mock.patch(NOW, return_value=now):
        call_command('generate_scheduled_trips', stdout=StringIO(), stderr=StringIO())


class GenerateTripsTests(TestCase):
    def setUp(self):
        self.company = Company.objects.first() or Company.objects.create(name='TestCo')
        self.route = Route.objects.create(
            company=self.company, name='A to B', start_point='A', end_point='B', price=100)
        self.driver = Driver.objects.create(
            name='D', phone_number='0700000000', bus_number='KAA 1', company=self.company)
        self.sch = TripSchedule.objects.create(
            route=self.route, driver=self.driver, capacity=30,
            days_of_week='0,1,2,3,4', departure_time=time(7, 0))

    def test_creates_weekday_trips_for_next_7_days(self):
        run(TUE_6AM)  # Tue Wed Thu Fri + next Mon
        self.assertEqual(Trip.objects.filter(schedule=self.sch).count(), 5)

    def test_rerun_creates_nothing_new(self):
        run(TUE_6AM)
        run(TUE_6AM)
        self.assertEqual(Trip.objects.filter(schedule=self.sch).count(), 5)

    def test_past_slot_today_is_skipped(self):
        run(TUE_8AM)  # Tuesday 07:00 already gone
        self.assertEqual(Trip.objects.filter(schedule=self.sch).count(), 4)

    def test_unavailable_driver_gets_no_trips(self):
        self.driver.is_available = False
        self.driver.save()
        run(TUE_6AM)
        self.assertEqual(Trip.objects.count(), 0)

    def test_driver_conflict_slot_is_skipped(self):
        Trip.objects.create(
            route=self.route, driver=self.driver, capacity=10, status='scheduled',
            departure_at=datetime(2030, 1, 2, 7, 0, tzinfo=NBO))
        run(TUE_6AM)
        self.assertEqual(Trip.objects.filter(schedule=self.sch).count(), 4)

    def test_inactive_schedule_is_ignored(self):
        self.sch.is_active = False
        self.sch.save()
        run(TUE_6AM)
        self.assertEqual(Trip.objects.count(), 0)

    def test_cancelled_generated_trip_is_not_regenerated(self):
        run(TUE_6AM)
        t = Trip.objects.filter(schedule=self.sch).first()
        t.status = 'cancelled'
        t.save()
        run(TUE_6AM)
        self.assertEqual(Trip.objects.filter(schedule=self.sch).count(), 5)

    def test_deleting_schedule_keeps_trips(self):
        run(TUE_6AM)
        self.sch.delete()
        self.assertEqual(Trip.objects.count(), 5)
        self.assertEqual(Trip.objects.filter(schedule__isnull=True).count(), 5)

    def test_cross_company_driver_is_invalid(self):
        other = Company.objects.exclude(pk=self.company.pk).first() or Company.objects.create(name='Other')
        self.driver.company = other
        self.driver.save()
        run(TUE_6AM)
        self.assertEqual(Trip.objects.count(), 0)
