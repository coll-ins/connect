from datetime import time
from unittest import mock

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from companies.models import Company, Route, Trip, TripSchedule
from drivers.models import Driver

CAN = 'companies.schedule_views.can_manage_company'


class ScheduleApiTests(APITestCase):
    def setUp(self):
        self.co = Company.objects.create(name='CoA')
        self.other = Company.objects.create(name='CoB')
        self.route = Route.objects.create(company=self.co, name='R', start_point='A', end_point='B', price=100)
        self.orow = Route.objects.create(company=self.other, name='R2', start_point='A', end_point='B', price=100)
        self.drv = Driver.objects.create(name='D', phone_number='0700000001', bus_number='K1', company=self.co)
        self.odrv = Driver.objects.create(name='E', phone_number='0700000002', bus_number='K2', company=self.other)
        self.c = APIClient()
        self.c.force_authenticate(user=get_user_model()(username='mgr'))
        self.body = {'company_id': self.co.id, 'route_id': self.route.id, 'driver_id': self.drv.id,
                     'capacity': 30, 'days_of_week': [0, 1, 2], 'departure_time': '06:30'}

    def post(self, **over):
        return self.c.post('/api/companies/schedules/create/', {**self.body, **over}, format='json')

    def test_unauthenticated_is_rejected(self):
        r = APIClient().post('/api/companies/schedules/create/', self.body, format='json')
        self.assertIn(r.status_code, (401, 403))

    @mock.patch(CAN, return_value=False)
    def test_unauthorized_company_is_403(self, _):
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(TripSchedule.objects.count(), 0)

    @mock.patch(CAN, return_value=True)
    def test_create_and_list(self, _):
        r = self.post()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['days_of_week'], [0, 1, 2])
        self.assertEqual(r.json()['departure_time'], '06:30')
        lst = self.c.get(f'/api/companies/{self.co.id}/schedules/')
        self.assertEqual(len(lst.json()), 1)

    @mock.patch(CAN, return_value=True)
    def test_other_company_route_or_driver_rejected(self, _):
        self.assertEqual(self.post(route_id=self.orow.id).status_code, 404)
        self.assertEqual(self.post(driver_id=self.odrv.id).status_code, 404)
        self.assertEqual(TripSchedule.objects.count(), 0)

    @mock.patch(CAN, return_value=True)
    def test_bad_input_is_400(self, _):
        for over in ({'capacity': 0}, {'capacity': 101}, {'days_of_week': []}, {'days_of_week': [7]},
                     {'days_of_week': 'mon'}, {'departure_time': '25:99'}, {'departure_time': ''},
                     {'start_date': '2030-02-01', 'end_date': '2030-01-01'}):
            self.assertEqual(self.post(**over).status_code, 400, over)

    @mock.patch(CAN, return_value=True)
    def test_duplicate_is_409(self, _):
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post().status_code, 409)

    @mock.patch(CAN, return_value=True)
    def test_pause_and_edit(self, _):
        sid = self.post().json()['id']
        r = self.c.patch(f'/api/companies/schedules/{sid}/', {'is_active': False, 'capacity': 14}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        s = TripSchedule.objects.get(pk=sid)
        self.assertFalse(s.is_active)
        self.assertEqual(s.capacity, 14)
        self.assertEqual(s.departure_time, time(6, 30))

    @mock.patch(CAN, return_value=True)
    def test_patch_cannot_move_to_other_company_driver(self, _):
        sid = self.post().json()['id']
        r = self.c.patch(f'/api/companies/schedules/{sid}/', {'driver_id': self.odrv.id}, format='json')
        self.assertEqual(r.status_code, 404)

    @mock.patch(CAN, return_value=True)
    def test_delete_keeps_generated_trips(self, _):
        sid = self.post().json()['id']
        s = TripSchedule.objects.get(pk=sid)
        Trip.objects.create(route=self.route, driver=self.drv, capacity=30, schedule=s,
                            departure_at='2030-01-01T06:30:00+03:00')
        self.assertEqual(self.c.delete(f'/api/companies/schedules/{sid}/').status_code, 204)
        self.assertEqual(Trip.objects.count(), 1)
        self.assertIsNone(Trip.objects.first().schedule)

    @mock.patch(CAN, return_value=False)
    def test_manage_unauthorized_is_403(self, _):
        s = TripSchedule.objects.create(route=self.route, driver=self.drv, days_of_week='0',
                                        departure_time=time(6, 0))
        self.assertEqual(self.c.patch(f'/api/companies/schedules/{s.id}/', {'is_active': False}, format='json').status_code, 403)
        self.assertEqual(self.c.delete(f'/api/companies/schedules/{s.id}/').status_code, 403)
        self.assertTrue(TripSchedule.objects.filter(pk=s.id).exists())