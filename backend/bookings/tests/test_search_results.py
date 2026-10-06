from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from bookings.models import Booking
from bookings.views import auditor_receipt_search, passenger_records
from companies.models import Company, Route, Trip
from drivers.models import Driver

User = get_user_model()


class SearchWithRealBookingsTests(APITestCase):

    def setUp(self):
        self.company = Company.objects.create(name="Express Line")
        self.other_company = Company.objects.create(name="Other Line")

        def mk(username, phone, role="passenger", company=None):
            return User.objects.create_user(
                username=username, password="password123",
                phone_number=phone, role=role, company=company,
            )

        self.auditor = mk("aud", "+254700000300", "company_auditor", self.company)
        self.pax_a = mk("pax_a", "+254700000301")
        self.pax_b = mk("pax_b", "+254700000302")

        def make_trip(company, name, driver_phone, bus):
            driver = Driver.objects.create(
                company=company, name=name, phone_number=driver_phone, bus_number=bus,
            )
            route = Route.objects.create(
                company=company, name=f"{name} route", price=Decimal("800.00"),
            )
            trip = Trip.objects.create(
                route=route, driver=driver,
                departure_at=timezone.now() + timezone.timedelta(hours=3),
                capacity=10,
            )
            return route, trip

        route1, trip1 = make_trip(self.company, "D1", "+254711000001", "KAA 001A")
        route2, trip2 = make_trip(self.other_company, "D2", "+254711000002", "KBB 002B")

        def book(user, route, trip, number):
            return Booking.objects.create(
                user=user, route=route, trip=trip, booking_number=number,
                total_amount=Decimal("800.00"), status="confirmed",
            )

        self.b_a = book(self.pax_a, route1, trip1, "BK1001")
        self.b_b = book(self.pax_b, route1, trip1, "BK1002")
        self.b_other = book(self.pax_a, route2, trip2, "BK2002")

    def _call(self, view, user, search):
        request = APIRequestFactory().get("/x/", {"search": search})
        force_authenticate(request, user=user)
        return view(request)

    def _numbers(self, response):
        return {r["booking_number"] for r in response.data}

    def test_auditor_finds_by_booking_number(self):
        r = self._call(auditor_receipt_search, self.auditor, "BK1001")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._numbers(r), {"BK1001"})

    def test_auditor_finds_by_username_and_phone(self):
        self.assertEqual(self._numbers(self._call(auditor_receipt_search, self.auditor, "pax_a")), {"BK1001"})
        self.assertEqual(self._numbers(self._call(auditor_receipt_search, self.auditor, "000302")), {"BK1002"})

    def test_auditor_cannot_see_other_company_bookings(self):
        r = self._call(auditor_receipt_search, self.auditor, "BK2002")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._numbers(r), set())

    def test_passenger_records_only_own_bookings(self):
        r = self._call(passenger_records, self.pax_a, "BK")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._numbers(r), {"BK1001", "BK2002"})

    def test_passenger_cannot_find_someone_elses_booking(self):
        r = self._call(passenger_records, self.pax_a, "BK1002")
        self.assertEqual(self._numbers(r), set())
