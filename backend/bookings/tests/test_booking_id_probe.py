"""Booking ids cannot be enumerated through the location endpoints."""
from unittest.mock import patch

from bookings.tests.test_seat_holds import SeatBase
from companies.models import Company
from django.contrib.auth import get_user_model

User = get_user_model()
URLS = ('/api/bookings/{}/live-location/', '/api/bookings/{}/reroute/')


class LocationEndpointProbeTests(SeatBase):
    def setUp(self):
        super().setUp()
        self.mine = self.booking(1, 'confirmed', user=self.passenger)
        other = Company.objects.create(name='Other Co', areas_served='Kisumu')
        self.other_mgr = User.objects.create_user(
            username='omgr', password='pw-123456', phone_number='+254711777001',
            company=other, role='company_manager')
        self.own_mgr = User.objects.create_user(
            username='mgr', password='pw-123456', phone_number='+254711777002',
            company=self.company, role='company_manager')

    def get(self, template, user, booking_id=None):
        self.client.force_authenticate(user)
        return self.client.get(template.format(booking_id or self.mine.id))

    @patch('companies.routing.road_line', return_value=([], 1.0))
    def test_a_booking_that_is_not_yours_looks_like_a_missing_one(self, _road):
        missing = self.mine.id + 9999
        for template in URLS:
            for label, user in (('stranger', self.user()), ('other company', self.other_mgr)):
                with self.subTest(url=template, caller=label):
                    refused = self.get(template, user)
                    absent = self.get(template, user, missing)
                    self.assertEqual(refused.status_code, 404)
                    self.assertEqual(refused.status_code, absent.status_code)
                    self.assertEqual(refused.data, absent.data)

    @patch('companies.routing.road_line', return_value=([], 1.0))
    def test_own_company_staff_keep_the_403(self, _road):
        other = self.user()
        stranger_booking = self.booking(1, 'confirmed', user=other)
        self.assertEqual(
            self.get('/api/bookings/{}/reroute/', self.own_mgr, stranger_booking.id).status_code, 403)


class StaffActionProbeTests(LocationEndpointProbeTests):
    """Boarding and cash confirmation answer an outsider exactly like a missing id."""

    def post(self, path, user, booking_id):
        self.client.force_authenticate(user)
        return self.client.post(path.format(booking_id), {'boarding_pin': '000000'}, format='json')

    def test_outsiders_cannot_tell_a_real_booking_from_a_missing_one(self):
        missing = self.mine.id + 9999
        for path in ('/api/bookings/{}/verify-boarding/', '/api/bookings/payments/{}/cash/confirm/'):
            for label, user in (('stranger', self.user()), ('other company', self.other_mgr)):
                with self.subTest(path=path, caller=label):
                    refused = self.post(path, user, self.mine.id)
                    absent = self.post(path, user, missing)
                    self.assertEqual(refused.status_code, 404)
                    self.assertEqual(refused.data['error'].rstrip('.'),
                                     absent.data['error'].rstrip('.'))

    def test_own_company_auditor_keeps_the_403(self):
        auditor = User.objects.create_user(
            username='aud', password='pw-123456', phone_number='+254711777003',
            company=self.company, role='company_auditor')
        self.assertEqual(
            self.post('/api/bookings/{}/verify-boarding/', auditor, self.mine.id).status_code, 403)
