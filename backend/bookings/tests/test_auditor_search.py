from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from bookings.views import auditor_receipt_search
from companies.models import Company

User = get_user_model()


class AuditorReceiptSearchTests(APITestCase):

    def setUp(self):
        self.company = Company.objects.create(name="Coast Bus", areas_served="Mombasa")
        self.auditor = User.objects.create_user(
            username="auditor", password="password123",
            phone_number="+254700000201", role="company_auditor",
            company=self.company,
        )
        self.passenger = User.objects.create_user(
            username="pax", password="password123",
            phone_number="+254700000202", role="passenger",
        )

    def _get(self, user, search):
        request = APIRequestFactory().get("/x/", {"search": search})
        force_authenticate(request, user=user)
        return auditor_receipt_search(request)

    def test_search_no_match_returns_200_not_500(self):
        self.assertEqual(self._get(self.auditor, "zzz-nothing").status_code, 200)

    def test_search_by_phone_fragment_returns_200(self):
        self.assertEqual(self._get(self.auditor, "254").status_code, 200)

    def test_empty_search_is_400(self):
        self.assertEqual(self._get(self.auditor, "").status_code, 400)

    def test_non_auditor_is_403(self):
        self.assertEqual(self._get(self.passenger, "x").status_code, 403)
