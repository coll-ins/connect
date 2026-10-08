from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from companies.models import Company

User = get_user_model()
PRIVILEGED = {"platform_admin", "company_manager", "company_operator",
              "company_auditor", "driver"}


class RedTeamSignupTests(APITestCase):
    def test_signup_cannot_self_assign_privileges(self):
        co = Company.objects.create(name="A", description="d", areas_served="N")
        for n, path in enumerate(("/api/users/signup/", "/api/users/register/")):
            with self.subTest(path=path):
                phone = f"+25473300900{n}"
                r = self.client.post(path, {
                    "username": f"evil{n}", "phone_number": phone,
                    "password": "Tr4velSafe-2026",
                    "role": "platform_admin", "is_superuser": True,
                    "is_staff": True, "company": co.id, "company_id": co.id,
                }, format="json")
                self.assertIn(r.status_code, (200, 201, 400, 404, 405), r.content)
                user = User.objects.filter(username=f"evil{n}").first()
                if user is None:
                    continue
                self.assertNotIn(user.role, PRIVILEGED)
                self.assertFalse(user.is_superuser)
                self.assertFalse(user.is_staff)
                self.assertIsNone(user.company_id)
