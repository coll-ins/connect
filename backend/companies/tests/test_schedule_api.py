from datetime import time
from unittest import mock

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from buses.models import Bus
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
        self.bus = Bus.objects.create(company=self.co, registration_number='KDA 001A', bus_number='1',
                                      vehicle_type='minibus_33', capacity=1)
        self.bus14 = Bus.objects.create(company=self.co, registration_number='KDA 002A', bus_number='2',
                                        vehicle_type='matatu_14', capacity=1)
        self.obus = Bus.objects.create(company=self.other, registration_number='KDB 001B', bus_number='1',
                                       vehicle_type='matatu_14', capacity=1)
        self.c = APIClient()
        self._gen = mock.patch('companies.schedule_views._generate_on_create', return_value=0)
        self._gen.start()
        self.addCleanup(self._gen.stop)
        self.c.force_authenticate(user=get_user_model()(username='mgr'))
        self.body = {'company_id': self.co.id, 'route_id': self.route.id, 'driver_id': self.drv.id,
                     'bus_id': self.bus.id, 'days_of_week': [0, 1, 2], 'departure_time': '06:30',
                     'auto_renew': True}

    def post(self, **over):
        return self.c.post('/api/companies/schedules/create/', {**self.body, **over}, format='json')

    def test_unauthenticated_is_rejected(self):
        r = APIClient().post('/api/companies/schedules/create/', self.body, format='json')
        self.assertIn(r.status_code, (401, 403))

    def test_company_operator_cannot_manage_templates(self):
        operator = get_user_model().objects.create(
            username='operator', role='company_operator', company=self.co)
        self.c.force_authenticate(user=operator)
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(
            self.c.get(f'/api/companies/{self.co.id}/schedules/').status_code,
            403,
        )

    def test_schedule_exceptions_are_visible_to_route_scoped_operator_only(self):
        from companies.models import TripSchedule

        other_route = Route.objects.create(
            company=self.co, name='Other route', start_point='C',
            end_point='D', price=100,
        )
        visible = TripSchedule.objects.create(
            route=self.route, driver=self.drv, days_of_week='0',
            departure_time=time(6, 30), auto_renew=True,
            driver_conflict_count=2,
        )
        TripSchedule.objects.create(
            route=other_route, driver=self.drv, days_of_week='0',
            departure_time=time(7, 30), auto_renew=True,
            driver_unavailable_count=1,
        )
        operator = get_user_model().objects.create(
            username='scoped_operator', role='company_operator',
            company=self.co, all_routes=False,
        )
        operator.assigned_routes.add(self.route)
        self.c.force_authenticate(user=operator)
        response = self.c.get(f'/api/companies/{self.co.id}/schedule-exceptions/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['schedule_id'] for item in response.data], [visible.id])
        self.assertEqual(response.data[0]['route_name'], self.route.name)
        self.assertEqual(response.data[0]['driver_conflict_count'], 2)

    @mock.patch(CAN, return_value=True)
    def test_manager_can_view_company_schedule_exceptions(self, _):
        from companies.models import TripSchedule

        self.c.force_authenticate(user=get_user_model().objects.create(
            username='exception_manager', role='company_manager', company=self.co,
        ))
        schedule = TripSchedule.objects.create(
            route=self.route, driver=self.drv, days_of_week='0',
            departure_time=time(6, 30), auto_renew=True,
            driver_unavailable_count=1,
        )
        response = self.c.get(f'/api/companies/{self.co.id}/schedule-exceptions/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]['schedule_id'], schedule.id)

    def test_other_company_cannot_view_schedule_exceptions(self):
        operator = get_user_model().objects.create(
            username='foreign_operator', role='company_operator', company=self.other)
        self.c.force_authenticate(user=operator)
        response = self.c.get(f'/api/companies/{self.co.id}/schedule-exceptions/')
        self.assertEqual(response.status_code, 403)

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
        self.assertEqual(r.json()['normal_interval_minutes'], 60)
        self.assertEqual(r.json()['rush_interval_minutes'], 30)
        self.assertTrue(r.json()['auto_renew'])
        lst = self.c.get(f'/api/companies/{self.co.id}/schedules/')
        self.assertEqual(len(lst.json()), 1)

    @mock.patch(CAN, return_value=True)
    @mock.patch('companies.schedule_views._generate_on_create', side_effect=RuntimeError('generator failed'))
    def test_create_rolls_back_and_returns_error_when_generation_fails(self, _generation, _):
        response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertIn('could not be generated', response.json()['error'])
        self.assertEqual(TripSchedule.objects.count(), 0)

    @mock.patch(CAN, return_value=True)
    def test_other_company_route_or_driver_rejected(self, _):
        self.assertEqual(self.post(route_id=self.orow.id).status_code, 404)
        self.assertEqual(self.post(driver_id=self.odrv.id).status_code, 404)
        self.assertEqual(self.post(bus_id=self.obus.id).status_code, 404)
        self.assertEqual(self.post(bus_id=None).status_code, 404)
        self.assertEqual(self.post(bus_id=self.bus.id + 0.5).status_code, 404)
        Bus.objects.filter(pk=self.bus14.pk).update(maintenance_status='maintenance')
        self.assertEqual(self.post(bus_id=self.bus14.id).status_code, 404)
        self.assertEqual(TripSchedule.objects.count(), 0)

    @mock.patch(CAN, return_value=True)
    def test_bad_input_is_400(self, _):
        for over in ({'days_of_week': []}, {'days_of_week': [7]},
                     {'days_of_week': 'mon'}, {'departure_time': '25:99'}, {'departure_time': ''},
                     {'start_date': '2030-02-01', 'end_date': '2030-01-01'},
                     {'normal_interval_minutes': 10},
                     {'rush_interval_minutes': 300},
                     {'normal_interval_minutes': 30, 'rush_interval_minutes': 60},
                     {'rush_start_time': '07:00'},
                     {'service_end_time': '06:30'},
                     {'service_end_time': '18:00', 'rush_start_time': '17:00', 'rush_end_time': '19:00'}):
            self.assertEqual(self.post(**over).status_code, 400, over)

    @mock.patch(CAN, return_value=True)
    def test_manual_schedule_requires_a_maximum_one_week_date_range(self, _):
        manual = {'auto_renew': False, 'start_date': '2030-01-01', 'end_date': '2030-01-07'}
        self.assertEqual(self.post(**manual).status_code, 201)
        self.assertEqual(
            self.post(auto_renew=False, start_date='2030-01-01', end_date='2030-01-08').status_code,
            400,
        )
        self.assertEqual(self.post(auto_renew=False).status_code, 400)

    @mock.patch(CAN, return_value=True)
    def test_rush_window_generates_configurable_frequency(self, _):
        r = self.post(
            service_end_time='09:00',
            rush_start_time='07:00',
            rush_end_time='08:00',
            normal_interval_minutes=60,
            rush_interval_minutes=30,
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['rush_start_time'], '07:00')
        self.assertEqual(r.json()['rush_end_time'], '08:00')

    @mock.patch(CAN, return_value=True)
    def test_duplicate_is_409(self, _):
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post().status_code, 409)

    @mock.patch(CAN, return_value=True)
    def test_pause_and_edit(self, _):
        sid = self.post().json()['id']
        r = self.c.patch(f'/api/companies/schedules/{sid}/', {'is_active': False, 'bus_id': self.bus14.id, 'capacity': 60}, format='json')
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
                         {'end_date': '2031-01-01', 'bus_id': self.bus14.id}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotIn('cancelled_trips', r.json())
        t.refresh_from_db()
        self.assertEqual(t.status, 'scheduled')
        self.assertEqual((t.bus_id, t.capacity), (self.bus14.id, 14))

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
        r = self._patch(sid, bus_id=self.bus14.id)
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
    def test_create_reports_generation_failure_without_persisting_schedule(self, _):
        self._gen.stop()
        with mock.patch('companies.schedule_views.regenerate_for_schedule', side_effect=RuntimeError('boom')):
            r = self.post()
        self.assertEqual(r.status_code, 500, r.content)
        self.assertIn('could not be generated', r.json()['error'])
        self.assertEqual(TripSchedule.objects.count(), 0)
        self.assertEqual(Trip.objects.count(), 0)
