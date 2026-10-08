from django.test import TestCase

from users.models import CustomUser
from users.serializers import UserSerializer
from users.views import serialize_session_user


class DisplayNameTests(TestCase):

    def test_signup_name_becomes_session_name(self):
        s = UserSerializer(data={
            "name": "Collins Otieno", "phone_number": "+254700000401", "password": 'Tr4velSafe-2026',
        })
        self.assertTrue(s.is_valid(), s.errors)
        user = s.save()
        self.assertEqual((user.first_name, user.last_name), ("Collins", "Otieno"))
        self.assertEqual(serialize_session_user(user)["name"], "Collins Otieno")

    def test_auto_username_never_shown_as_name(self):
        s = UserSerializer(data={"phone_number": "+254700000402", "password": 'Tr4velSafe-2026'})
        self.assertTrue(s.is_valid(), s.errors)
        user = s.save()
        self.assertTrue(user.username.startswith("user_"))
        self.assertEqual(serialize_session_user(user)["name"], "+254700000402")

    def test_human_chosen_username_is_kept(self):
        user = CustomUser.objects.create_user(
            username="collins_driver", password="x", phone_number="+254700000403",
        )
        self.assertEqual(user.display_name, "collins_driver")
