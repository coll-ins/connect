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
        self._gen = mock.patch('companies.schedule_views._generate_on_create', return_value=0)
        self._gen.start()
        self.addCleanup(self._gen.stop)
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


    @mock.patch(CAN, return_value=False)
    def test_manage_unauthorized_is_403(self, _):
        s = TripSchedule.objects.create(route=self.route, driver=self.drv, days_of_week='0',
                                        departure_time=time(6, 0))
        self.assertEqual(self.c.patch(f'/api/companies/schedules/{s.id}/', {'is_active': False}, format='json').status_code, 403)
        self.assertEqual(self.c.delete(f'/api/companies/schedules/{s.id}/').status_code, 403)
        self.assertTrue(TripSchedule.objects.filter(pk=s.id).exists())





    @mock.patch(CAN, return_value=True)
    def test_time_edit_cancels_old_slots(self, _):
        sid = self.post().json()['id']
        s = TripSchedule.objects.get(pk=sid)
        t = self._trip(s, '2030-01-01T06:30:00+03:00')
        r = self.c.patch(f'/api/companies/schedules/{sid}/', {'departure_time': '07:00'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['cancelled_trips'], 1)
        t.refresh_from_db()
        self.assertEqual(t.status, 'cancelled')

    @mock.patch(CAN, return_value=True)
    def test_days_edit_cancels_old_slots(self, _):
        sid = self.post().json()['id']
        s = TripSchedule.objects.get(pk=sid)
        t = self._trip(s, '2030-01-01T06:30:00+03:00')
        r = self.c.patch(f'/api/companies/schedules/{sid}/', {'days_of_week': [3, 4]}, format='json')
        self.assertEqual(r.json()['cancelled_trips'], 1)
        t.refresh_from_db()
        self.assertEqual(t.status, 'cancelled')



    def _trip(self, s, when, status='scheduled'):
        return Trip.objects.create(route=self.route, driver=self.drv, capacity=30, schedule=s,
                                   departure_at=when, status=status)

    @mock.patch(CAN, return_value=True)
    def test_delete_cancels_untouched_future_trips(self, _):
        sid = self.post().json()['id']
        s = TripSchedule.objects.get(pk=sid)
        t = self._trip(s, '2030-01-01T06:30:00+03:00')
        r = self.c.delete(f'/api/companies/schedules/{sid}/')
        self.assertEqual(r.json(), {'cancelled_trips': 1, 'kept_trips': 0})
        t.refresh_from_db()
        self.assertEqual(t.status, 'cancelled')
        self.assertIsNone(t.schedule)

    @mock.patch(CAN, return_value=True)
    def test_delete_leaves_past_and_boarding_trips(self, _):
        sid = self.post().json()['id']
        s = TripSchedule.objects.get(pk=sid)
        past = self._trip(s, '2020-01-01T06:30:00+03:00')
        boarding = self._trip(s, '2030-01-01T06:30:00+03:00', status='boarding')
        r = self.c.delete(f'/api/companies/schedules/{sid}/')
        self.assertEqual(r.json(), {'cancelled_trips': 0, 'kept_trips': 0})
        past.refresh_from_db()
        boarding.refresh_from_db()
        self.assertEqual(past.status, 'scheduled')
        self.assertEqual(boarding.status, 'boarding')

    @mock.patch(CAN, return_value=True)
    def test_pause_cancels_future_trips(self, _):
        sid = self.post().json()['id']
        s = TripSchedule.objects.get(pk=sid)
        t = self._trip(s, '2030-01-01T06:30:00+03:00')
        r = self.c.patch(f'/api/companies/schedules/{sid}/', {'is_active': False}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['cancelled_trips'], 1)
        t.refresh_from_db()
        self.assertEqual(t.status, 'cancelled')

    @mock.patch(CAN, return_value=True)
    def test_time_and_days_edit_cancel_old_slots(self, _):
        sid = self.post().json()['id']
        s = TripSchedule.objects.get(pk=sid)
        t1 = self._trip(s, '2030-01-01T06:30:00+03:00')
        r = self.c.patch(f'/api/companies/schedules/{sid}/', {'departure_time': '07:00'}, format='json')
        self.assertEqual(r.json()['cancelled_trips'], 1)
        g1 = r.json()['generated_trips']
        t1.refresh_from_db()
        self.assertEqual(t1.status, 'cancelled')
        t2 = self._trip(s, '2030-01-02T07:00:00+03:00')
        r = self.c.patch(f'/api/companies/schedules/{sid}/', {'days_of_week': [3, 4]}, format='json')
        self.assertEqual(r.json()['cancelled_trips'], 1 + g1)
        t2.refresh_from_db()
        self.assertEqual(t2.status, 'cancelled')
        from django.utils import timezone
        tz = timezone.get_current_timezone()
        live = Trip.objects.filter(schedule_id=sid, status='scheduled')
        self.assertTrue(live.exists())
        self.assertTrue(all(t.departure_at.astimezone(tz).weekday() in (3, 4) for t in live))

    @mock.patch(CAN, return_value=True)
    def test_cosmetic_edit_cancels_nothing(self, _):
        sid = self.post().json()['id']
        s = TripSchedule.objects.get(pk=sid)
        t = self._trip(s, '2030-01-01T06:30:00+03:00')
        r = self.c.patch(f'/api/companies/schedules/{sid}/',
                         {'end_date': '2031-01-01', 'capacity': 20}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotIn('cancelled_trips', r.json())
        t.refresh_from_db()
        self.assertEqual(t.status, 'scheduled')

    @mock.patch(CAN, return_value=True)
    def test_booked_trip_is_kept_and_counted(self, _):
        from bookings.models import Booking
        sid = self.post().json()['id']
        s = TripSchedule.objects.get(pk=sid)
        free = self._trip(s, '2030-01-01T06:30:00+03:00')
        booked = self._trip(s, '2030-01-02T06:30:00+03:00')
        pax = get_user_model().objects.create(username='pax')
        Booking.objects.create(user=pax, route=self.route, trip=booked, pickup_location='Stage')
        r = self.c.delete(f'/api/companies/schedules/{sid}/')
        self.assertEqual(r.json(), {'cancelled_trips': 1, 'kept_trips': 1})
        free.refresh_from_db()
        booked.refresh_from_db()
        self.assertEqual(free.status, 'cancelled')
        self.assertEqual(booked.status, 'scheduled')

    def _seed(self, sid):
        from io import StringIO
        from django.core.management import call_command
        call_command('generate_scheduled_trips', stdout=StringIO(), stderr=StringIO())
        n = Trip.objects.filter(schedule_id=sid, status='scheduled').count()
        self.assertGreater(n, 0)
        return n

    def _live_times(self, sid):
        from django.utils import timezone
        tz = timezone.get_current_timezone()
        return {t.departure_at.astimezone(tz).time()
                for t in Trip.objects.filter(schedule_id=sid, status='scheduled')}

    def _patch(self, sid, **body):
        return self.c.patch(f'/api/companies/schedules/{sid}/', body, format='json')

    @mock.patch(CAN, return_value=True)
    def test_time_edit_generates_new_slots(self, _):
        sid = self.post(days_of_week=[0, 1, 2, 3, 4, 5, 6]).json()['id']
        self._seed(sid)
        self.assertEqual(self._live_times(sid), {time(6, 30)})
        r = self._patch(sid, departure_time='07:00')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._live_times(sid), {time(7, 0)})
        self.assertEqual(r.json()['generated_trips'],
                         Trip.objects.filter(schedule_id=sid, status='scheduled').count())

    @mock.patch(CAN, return_value=True)
    def test_reverting_time_revives_old_slots(self, _):
        sid = self.post(days_of_week=[0, 1, 2, 3, 4, 5, 6]).json()['id']
        n0 = self._seed(sid)
        self._patch(sid, departure_time='07:00')
        self._patch(sid, departure_time='06:30')
        self.assertEqual(self._live_times(sid), {time(6, 30)})
        self.assertEqual(Trip.objects.filter(schedule_id=sid, status='scheduled').count(), n0)

    @mock.patch(CAN, return_value=True)
    def test_resume_restores_cancelled_trips(self, _):
        sid = self.post(days_of_week=[0, 1, 2, 3, 4, 5, 6]).json()['id']
        n0 = self._seed(sid)
        self._patch(sid, is_active=False)
        self.assertEqual(Trip.objects.filter(schedule_id=sid, status='scheduled').count(), 0)
        r = self._patch(sid, is_active=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Trip.objects.filter(schedule_id=sid, status='scheduled').count(), n0)

    @mock.patch(CAN, return_value=True)
    def test_booked_old_slot_kept_and_new_slots_generated(self, _):
        from bookings.models import Booking
        sid = self.post(days_of_week=[0, 1, 2, 3, 4, 5, 6]).json()['id']
        self._seed(sid)
        booked = Trip.objects.filter(schedule_id=sid, status='scheduled').order_by('departure_at').first()
        pax = get_user_model().objects.create(username='pax2')
        Booking.objects.create(user=pax, route=self.route, trip=booked, pickup_location='Stage')
        r = self._patch(sid, departure_time='07:00')
        self.assertEqual(r.json()['kept_trips'], 1)
        booked.refresh_from_db()
        self.assertEqual(booked.status, 'scheduled')
        self.assertEqual(self._live_times(sid), {time(6, 30), time(7, 0)})
        self.assertGreater(r.json()['generated_trips'], 0)

    @mock.patch(CAN, return_value=True)
    def test_cosmetic_edit_generates_nothing(self, _):
        sid = self.post(days_of_week=[0, 1, 2, 3, 4, 5, 6]).json()['id']
        n0 = self._seed(sid)
        r = self._patch(sid, capacity=20)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('generated_trips', r.json())
        self.assertEqual(Trip.objects.filter(schedule_id=sid).count(), n0)

    @mock.patch(CAN, return_value=True)
    def test_create_generates_trips(self, _):
        self._gen.stop()
        r = self.post()
        self.assertEqual(r.status_code, 201, r.content)
        sid = r.json()['id']
        live = Trip.objects.filter(schedule_id=sid, status='scheduled')
        self.assertGreater(r.json()['generated_trips'], 0)
        self.assertEqual(r.json()['generated_trips'], live.count())
        from django.utils import timezone
        tz = timezone.get_current_timezone()
        for t in live:
            local = t.departure_at.astimezone(tz)
            self.assertIn(local.weekday(), (0, 1, 2))
            self.assertEqual(local.time(), time(6, 30))

    @mock.patch(CAN, return_value=True)
    def test_create_then_nightly_command_adds_nothing(self, _):
        from io import StringIO
        from django.core.management import call_command
        self._gen.stop()
        r = self.post()
        sid = r.json()['id']
        self.assertGreater(r.json()['generated_trips'], 0)
        n = Trip.objects.filter(schedule_id=sid).count()
        call_command('generate_scheduled_trips', stdout=StringIO(), stderr=StringIO())
        self.assertEqual(Trip.objects.filter(schedule_id=sid).count(), n)

    @mock.patch(CAN, return_value=True)
    def test_create_survives_generation_failure(self, _):
        self._gen.stop()
        with mock.patch('companies.schedule_views.regenerate_for_schedule', side_effect=RuntimeError('boom')):
            r = self.post()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['generated_trips'], 0)
        self.assertEqual(TripSchedule.objects.count(), 1)
