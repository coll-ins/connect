"""City Shuttle Kamangu buses load at Archives: the trip runs from there by GPS."""
import importlib
from datetime import timedelta
from unittest import mock

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from bookings.departure import auto_depart_on_movement
from bookings.models import Booking
from companies.models import Company, Route, Trip
from drivers.models import Driver

migration = importlib.import_module('companies.migrations.0022_city_shuttle_archives_terminus')


class ArchivesTerminusTests(TestCase):
    def setUp(self):
        # The real routes, as migrations 0021 and 0022 left them.
        self.co = Company.objects.get(name='CityShuttle')
        migration.install(apps, None)  # running it again changes nothing
        self.out = Route.objects.get(company=self.co, name='CBD to Kamangu')

    def names(self, route):
        return list(route.pickup_stages.filter(is_active=True).order_by('order', 'id')
                    .values_list('name', flat=True))

    def test_archives_starts_the_way_out_and_ends_the_way_back(self):
        out = self.names(self.out)
        self.assertEqual(out[:5], ['Archives', 'Kencom', 'Kenyatta National Hospital',
                                   'Coptic Hospital', 'Prestige Plaza'])
        self.assertEqual(out.count('Archives'), 1)
        self.assertEqual(self.names(Route.objects.get(company=self.co, name='Kamangu to CBD'))[-2:], ['Kencom', 'Archives'])

    def test_board_at_archives_leave_and_rider_at_prestige_is_told(self):
        driver = Driver.objects.create(company=self.co, name='George', phone_number='+254712300099',
                                       bus_number='KBE 465S')
        trip = Trip.objects.create(route=self.out, driver=driver, status='scheduled', capacity=33,
                                   departure_at=timezone.now() + timedelta(minutes=20))
        brian = get_user_model().objects.create_user(username='brian', password='x',
                                                     phone_number='+254712300098')
        prestige = self.out.pickup_stages.get(name='Prestige Plaza')
        Booking.objects.create(user=brian, route=self.out, trip=trip, status='confirmed',
                               pickup_stage=prestige, pickup_location=prestige.name)

        def fix(lat, lng, prev=None):
            prev = prev or (lat, lng)
            with mock.patch('notifications.push.notify_users') as sent, \
                    mock.patch('notifications.sms.send_departure_sms'), \
                    self.captureOnCommitCallbacks(execute=True):
                auto_depart_on_movement(driver, prev[0], prev[1], lat, lng)
            trip.refresh_from_db()
            return sent

        sent = fix(-1.28505, 36.82610)  # standing in front of Archives
        self.assertEqual(trip.status, 'boarding')
        self.assertIn('at Archives', sent.call_args.args[2])

        away = (-1.2872, 36.8228)  # Haile Selassie side, over 150 m from Archives
        sent = fix(*away, prev=away)
        self.assertEqual(trip.status, 'departed')
        self.assertEqual((sent.call_args.args[0], sent.call_args.args[1]), ([brian.id], 'Your bus has left'))

        coptic = self.out.pickup_stages.get(name='Coptic Hospital')
        sent = fix(float(coptic.latitude), float(coptic.longitude))
        self.assertEqual((sent.call_args.args[0], sent.call_args.args[1]),
                         ([brian.id], 'Get ready: your bus is next'))
