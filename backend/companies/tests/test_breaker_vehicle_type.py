from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APITestCase
from buses.models import Bus
from companies.models import Trip, TripSchedule
from companies.tests.test_trip_bus import TripBusTests
from drivers.models import Driver


class BreakerVehicleType(APITestCase):
    setUp = TripBusTests.setUp
    _bus = TripBusTests._bus

    def _post(self, vt, drv=None):
        return self.client.post('/api/companies/trips/create/', {
            'company_id': self.co.id, 'route_id': self.route.id, 'driver_id': (drv or self.drv).id,
            'departure_at': self.when.isoformat(), 'vehicle_type': vt}, format='json')

    def test_list_vehicle_type_is_400_not_500(self):
        self.drv.bus_number = 'KDB 200B'; self.drv.save()
        self.client.raise_request_exception = False
        self.assertEqual(self._post(['bus_51']).status_code, 400)
        self.assertEqual(self._post({'a': 1}).status_code, 400)

    def test_schedule_list_vehicle_type_is_400_not_500(self):
        self.client.raise_request_exception = False
        r = self.client.post('/api/companies/schedules/create/', {
            'company_id': self.co.id, 'route_id': self.route.id, 'driver_id': self.drv.id,
            'vehicle_type': ['x'], 'days_of_week': [0], 'departure_time': '06:00'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_failed_request_does_not_retype_bus(self):
        b = Bus.objects.get(pk=self.bus51.pk)
        b.maintenance_status = 'maintenance'; b.save()
        self.drv.bus_number = '51'; self.drv.save()
        self._post('matatu_14')
        self.assertEqual(Bus.objects.get(pk=b.pk).vehicle_type, 'bus_51')

    def test_bus_with_active_schedule_not_retyped(self):
        self.drv.bus_number = '51'; self.drv.save()
        TripSchedule.objects.create(route=self.route, driver=self.drv, bus=self.bus51,
            capacity=51, days_of_week='0,1,2,3,4,5,6', departure_time='06:00')
        self.client.raise_request_exception = False
        self._post('matatu_14')
        self.assertEqual(Bus.objects.get(pk=self.bus51.pk).vehicle_type, 'bus_51')
