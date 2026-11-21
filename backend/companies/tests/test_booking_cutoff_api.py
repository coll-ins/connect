"""Cut-off aware trip list, per-company booking settings, stage seat summary (plan V2.6)."""
import datetime as dt

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import BoardingEvent
from bookings.tests.test_seat_holds import SeatBase
from companies.models import Company, Route, Trip

User = get_user_model()
MIN = dt.timedelta(minutes=1)


class CutoffBase(SeatBase):
    capacity = 10

    def setUp(self):
        super().setUp()
        self.mgr = User.objects.create_user(
            username='mgr', password='pw-123456', phone_number='+254711555001',
            company=self.company, role='company_manager')
        self.other_co = Company.objects.create(name='Far Co', areas_served='Kisumu')
        self.other_mgr = User.objects.create_user(
            username='omgr', password='pw-123456', phone_number='+254711555002',
            company=self.other_co, role='company_manager')

    def trip_at(self, minutes, status='scheduled', route=None):
        return Trip.objects.create(
            route=route or self.route, driver=self.driver, capacity=self.capacity,
            status=status, departure_at=timezone.now() + minutes * MIN)

    def listed_ids(self, user=None):
        client = APIClient()
        if user:
            client.force_authenticate(user)
        resp = client.get('/api/companies/trips/')
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        return {row['id'] for row in rows}, {row['id']: row for row in rows}


class TripListCutoffTests(CutoffBase):
    def test_trip_list_hides_trips_inside_company_cutoff(self):
        inside = self.trip_at(10)
        outside = self.trip_at(20)
        ids, _ = self.listed_ids()
        self.assertIn(outside.id, ids)
        self.assertNotIn(inside.id, ids)

    def test_cutoff_is_per_company(self):
        Company.objects.filter(pk=self.company.pk).update(booking_cutoff_minutes=60)
        far_route = Route.objects.create(
            company=self.other_co, name='Far', start_point='A', end_point='B', price=100)
        ours = self.trip_at(30)
        theirs = self.trip_at(30, route=far_route)  # default 15 minutes
        ids, _ = self.listed_ids()
        self.assertNotIn(ours.id, ids)
        self.assertIn(theirs.id, ids)

    def test_late_boarding_trip_is_no_longer_listed(self):
        late = self.trip_at(-30, status='boarding')
        self.assertNotIn(late.id, self.listed_ids()[0])

    def test_staff_still_see_trips_inside_the_cutoff(self):
        inside = self.trip_at(5)
        self.assertIn(inside.id, self.listed_ids(self.mgr)[0])

    def test_rows_carry_the_booking_window(self):
        self.booking(3, 'confirmed')
        trip = self.trip_at(40)
        _, rows = self.listed_ids()
        row = rows[trip.id]
        self.assertTrue(row['booking_open'])
        self.assertEqual(row['seats_available'], 10)
        self.assertEqual(row['booking_closes_at'], trip.departure_at - 15 * MIN)
        self.assertEqual(rows[self.trip.id]['seats_available'], 7)


class BookingSettingsTests(CutoffBase):
    URL = '/api/companies/booking-settings/'

    def patch(self, user, value):
        self.client.force_authenticate(user)
        return self.client.patch(self.URL, {'booking_cutoff_minutes': value}, format='json')

    def test_manager_reads_and_changes_own_company_only(self):
        self.client.force_authenticate(self.mgr)
        self.assertEqual(self.client.get(self.URL).data, {'booking_cutoff_minutes': 15})
        self.assertEqual(self.patch(self.mgr, 30).data, {'booking_cutoff_minutes': 30})
        self.company.refresh_from_db()
        self.other_co.refresh_from_db()
        self.assertEqual((self.company.booking_cutoff_minutes,
                          self.other_co.booking_cutoff_minutes), (30, 15))

    def test_range_is_zero_to_the_configured_maximum(self):
        for value in (0, 240):
            self.assertEqual(self.patch(self.mgr, value).status_code, 200)
        for value in (-1, 241, 'ten', 1.5, True, None):
            with self.subTest(value=value):
                self.assertEqual(self.patch(self.mgr, value).status_code, 400)
        self.company.refresh_from_db()
        self.assertEqual(self.company.booking_cutoff_minutes, 240)

    def test_only_a_company_manager_may_use_it(self):
        op = User.objects.create_user(
            username='op', password='pw-123456', phone_number='+254711555003',
            company=self.company, role='company_operator')
        for user in (op, self.passenger, self.staff):
            with self.subTest(user=user.username):
                self.client.force_authenticate(user)
                self.assertEqual(self.client.get(self.URL).status_code, 403)
                self.assertEqual(self.patch(user, 5).status_code, 403)
        self.assertEqual(APIClient().get(self.URL).status_code, 403)


class SeatSummaryTests(CutoffBase):
    def url(self, trip=None):
        return f'/api/companies/trips/{(trip or self.trip).id}/seat-summary/'

    def get(self, user, trip=None):
        self.client.force_authenticate(user)
        return self.client.get(self.url(trip))

    def test_summary_counts_and_matches_the_walkin_check(self):
        confirmed = self.booking(3, 'confirmed')
        BoardingEvent.objects.create(booking=confirmed, trip=self.trip, method='pin',
                                     verified_by=self.mgr)
        self.booking(2, 'pending', timezone.now() + 5 * MIN)
        self.booking(4, 'pending', timezone.now() - MIN)   # expired: frees its seats
        resp = self.get(self.mgr)
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.data
        self.assertEqual(
            (d['trip_id'], d['capacity'], d['confirmed_seats'], d['pending_seats'],
             d['boarded_seats'], d['open_seats']),
            (self.trip.id, 10, 3, 2, 3, 5))
        self.assertIsNotNone(d['pending_expires_at'])
        from bookings.services import seats_taken
        self.assertEqual(d['open_seats'], self.trip.capacity - seats_taken(self.trip))
        self.assertEqual(d['by_stage'], [
            {'stage_id': self.stage.id, 'name': 'Kencom', 'booked_seats': 5}])

    def test_online_and_walkup_windows(self):
        scheduled_open = self.get(self.mgr).data
        self.assertEqual((scheduled_open['online_open'], scheduled_open['walkup_allowed']),
                         (True, False))
        closing = self.trip_at(5)
        closed = self.get(self.mgr, closing).data
        self.assertEqual((closed['online_open'], closed['walkup_allowed']), (False, True))
        boarding = self.trip_at(2, status='boarding')
        self.assertEqual(self.get(self.mgr, boarding).data['walkup_allowed'], True)

    def test_seat_summary_other_company_404(self):
        for user in (self.other_mgr, self.passenger):
            self.assertEqual(self.get(user).status_code, 404)
        self.assertEqual(self.get(self.mgr, self.trip_at(60)).status_code, 200)
        missing = self.client.get('/api/companies/trips/999999/seat-summary/')
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.data, self.get(self.other_mgr).data)

    def test_operator_without_the_route_gets_404_and_the_trips_driver_gets_200(self):
        op = User.objects.create_user(
            username='op', password='pw-123456', phone_number='+254711555004',
            company=self.company, role='company_operator', all_routes=False)
        self.assertEqual(self.get(op).status_code, 404)
        op.assigned_routes.add(self.route)
        self.assertEqual(self.get(op).status_code, 200)
        drv = User.objects.create_user(
            username='drv', password='pw-123456', phone_number=self.driver.phone_number,
            company=self.company, role='driver')
        self.assertEqual(self.get(drv).status_code, 200)
        self.assertEqual(self.get(self.staff).status_code, 200)
