"""Every trip runs on a real bus: seats come from the bus, never the request."""
from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking
from buses.models import Bus
from companies.models import Company, Route, Trip, TripSchedule
from companies.trip_generation import regenerate_for_schedule
from drivers.models import Driver

User = get_user_model()


class TripBusTests(APITestCase):
    def setUp(self):
        self.co = Company.objects.create(name='Metro')
        self.other = Company.objects.create(name='Other')
        self.mgr = User.objects.create_user(
            username='mgr', password='x', phone_number='+254700000801',
            company=self.co, role='company_manager',
        )
        self.pax = User.objects.create_user(
            username='pax', password='x', phone_number='+254700000802', first_name='Amina',
        )
        self.route = Route.objects.create(company=self.co, name='CBD-Kikuyu', start_point='CBD',
                                          end_point='Kikuyu', price=Decimal('100'))
        self.drv = Driver.objects.create(name='Collins Maina', phone_number='+254700000803',
                                         bus_number='OLD', company=self.co)
        self.drv2 = Driver.objects.create(name='Jane W', phone_number='+254700000804',
                                          bus_number='OLD2', company=self.co)
        self.bus51 = self._bus('bus_51', 'KDA 551A', '51')
        self.bus14 = self._bus('matatu_14', 'KDA 514A', '14')
        self.when = (timezone.now() + timedelta(days=1)).replace(microsecond=0)
        self.client.force_authenticate(self.mgr)

    def _bus(self, vehicle_type, plate, fleet, company=None, capacity=1):
        return Bus.objects.create(company=company or self.co, registration_number=plate,
                                  bus_number=fleet, vehicle_type=vehicle_type, capacity=capacity)

    def _create(self, **over):
        body = {'company_id': self.co.id, 'route_id': self.route.id, 'driver_id': self.drv.id,
                'departure_at': self.when.isoformat(), 'bus_id': self.bus51.id, **over}
        return self.client.post('/api/companies/trips/create/', body, format='json')

    def test_bus_type_fixes_the_seat_count(self):
        self.assertEqual((self.bus51.capacity, self.bus14.capacity), (51, 14))
        other = self._bus('other', 'KDA 536A', '36', capacity=36)
        self.assertEqual(other.capacity, 36)

    def test_trip_seats_come_from_the_bus_not_the_request(self):
        r = self._create(capacity=60)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()['capacity'], r.json()['bus_plate']), (51, 'KDA 551A'))
        self.assertEqual(Trip.objects.get(pk=r.json()['id']).capacity, 51)

    def test_trip_needs_a_bus_of_this_company_that_is_free(self):
        self.assertEqual(self._create(bus_id=None).status_code, 400)
        # A float must not be truncated into some other bus's id.
        self.assertEqual(self._create(bus_id=self.bus51.id + 0.5).status_code, 409)
        theirs = self._bus('bus_51', 'KDB 551B', '51', company=self.other)
        self.assertEqual(self._create(bus_id=theirs.id).status_code, 409)
        self.assertEqual(self._create().status_code, 201)
        # Same bus, same time, other driver: refused. Another bus: fine.
        self.assertEqual(self._create(driver_id=self.drv2.id).status_code, 409)
        self.assertEqual(self._create(driver_id=self.drv2.id, bus_id=self.bus14.id).status_code, 201)

    def test_bus_api_type_sets_seats_and_downgrade_is_guarded(self):
        r = self.client.post('/api/buses/', {'registration_number': 'kdc 067c', 'bus_number': '67',
                                             'vehicle_type': 'bus_67', 'capacity': 99}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()['capacity'], r.json()['plan_verified']), (67, True))
        r = self.client.post('/api/buses/', {'registration_number': 'KDC 036C', 'bus_number': 'E9',
                                             'vehicle_type': 'other'}, format='json')
        self.assertEqual(r.status_code, 400)

        trip = Trip.objects.get(pk=self._create().json()['id'])
        Booking.objects.create(user=self.pax, route=self.route, driver=self.drv, trip=trip,
                               pickup_location='CBD', seats=20, total_amount=Decimal('2000'),
                               status='confirmed')
        url = f'/api/buses/{self.bus51.id}/'
        self.assertEqual(self.client.patch(url, {'vehicle_type': 'matatu_14'}, format='json').status_code, 409)
        self.assertEqual(Bus.objects.get(pk=self.bus51.pk).capacity, 51)
        self.assertEqual(self.client.patch(url, {'vehicle_type': 'minibus_27'}, format='json').status_code, 200)
        trip.refresh_from_db()
        self.assertEqual(trip.capacity, 27)
        self.assertEqual(self.client.delete(url).status_code, 409)

    def test_seat_map_shows_the_bus_and_driver(self):
        trip = Trip.objects.get(pk=self._create(bus_id=self.bus14.id).json()['id'])
        self.client.force_authenticate(self.pax)
        data = self.client.get(f'/api/bookings/trips/{trip.id}/seat-map/').json()
        self.assertEqual(data['bus'], {'fleet_number': '14', 'plate': 'KDA 514A', 'vehicle_type': 'matatu_14'})
        self.assertEqual(data['driver_name'], 'Collins Maina')
        self.assertTrue(data['plan_verified'])
        self.assertEqual(data['layout'][0], [1, 2, None, 'D'])

    def test_schedule_trips_run_on_its_bus_and_skip_a_busy_bus(self):
        sch = TripSchedule.objects.create(route=self.route, driver=self.drv, bus=self.bus14,
                                          capacity=99, days_of_week='0,1,2,3,4,5,6',
                                          departure_time=time(23, 59), auto_renew=True)
        self.assertEqual(sch.capacity, 14)
        counts = regenerate_for_schedule(sch, days=2)
        trips = Trip.objects.filter(schedule=sch)
        self.assertGreater(trips.count(), 0)
        self.assertTrue(all(t.bus_id == self.bus14.id and t.capacity == 14 for t in trips))
        # The same bus on a second schedule at the same times: skipped.
        sch2 = TripSchedule.objects.create(route=self.route, driver=self.drv2, bus=self.bus14,
                                           capacity=1, days_of_week='0,1,2,3,4,5,6',
                                           departure_time=time(23, 59), auto_renew=True)
        counts = regenerate_for_schedule(sch2, days=2)
        self.assertEqual(counts['created'], 0)
        self.assertEqual(counts['bus_conflict'], trips.count())
