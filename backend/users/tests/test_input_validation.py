from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from connect.validation import free_text, kenyan_mobile, person_name, place


class PhoneTests(SimpleTestCase):
    def test_accepts_every_kenyan_mobile_spelling(self):
        for raw in ('0712345678', '0712 345 678', '+254712345678', '254712345678',
                    '0112345678', '+254 112 345 678', '(0712) 345-678'):
            with self.subTest(raw=raw):
                self.assertIn(kenyan_mobile(raw), {'+254712345678', '+254112345678'})

    def test_rejects_numbers_that_cannot_be_called(self):
        for raw in ('', '12', '0712', '07123456789', '0212345678', '+255712345678',
                    '07l2345678', 'call me', '0700000000', '+254711111111'):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                kenyan_mobile(raw)


class PlaceTests(SimpleTestCase):
    def test_accepts_real_places(self):
        for raw in ('CBD', 'Westlands', 'Kencom, Moi Avenue', "Murang'a", 'JKIA Terminal 1A',
                    '4th Ngong Avenue', 'Nyahururu', 'Kisumu (Kibuye Market)', 'Mlolongo'):
            with self.subTest(raw=raw):
                self.assertEqual(place(raw), raw)

    def test_rejects_nonsense(self):
        for raw in ('', 'x', '12345', 'asdfgh', 'test', 'n/a', 'kkkkk', 'xkcdvbn town',
                    '<script>', 'hhhh', 'Westlands_1', 'qwerty'):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                place(raw)

    def test_optional_place_may_be_blank(self):
        self.assertEqual(place('  ', required=False), '')


class NameAndTextTests(SimpleTestCase):
    def test_names(self):
        self.assertEqual(person_name('  Wanjiru   Kamau '), 'Wanjiru Kamau')
        self.assertEqual(person_name("Ng'ang'a O'Brien-Otieno"), "Ng'ang'a O'Brien-Otieno")
        for raw in ('Wanjiru', 'J Kamau', 'Agent 47', 'asdf ghjk', 'Test User'):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                person_name(raw)

    def test_free_text(self):
        self.assertEqual(free_text('Box of shoes, handle with care'), 'Box of shoes, handle with care')
        self.assertEqual(free_text('Bus broke down at Mlolongo, strengths aside'), 'Bus broke down at Mlolongo, strengths aside')
        for raw in ('', '...', 'sdfghjkl', 'ok ok ok', 'test', 'aaaaaa bus'):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                free_text(raw)


class SignupRejectsNonsenseTests(SimpleTestCase):
    databases = frozenset({'default'})

    def _signup(self, **over):
        from rest_framework.test import APIClient
        body = {'name': 'Amina Hassan', 'phone_number': '0712000111', 'location': 'Westlands',
                'password': 'StrongPassword123!', 'accept_terms': True, **over}
        return APIClient().post('/api/users/register/', body, format='json')

    def test_bad_phone_location_or_name_is_refused_with_a_reason(self):
        for over, field in (({'phone_number': '12'}, 'phone_number'),
                            ({'phone_number': '0700000000'}, 'phone_number'),
                            ({'location': 'asdfgh'}, 'location'),
                            ({'name': 'Qwer Tyui'}, 'name')):
            with self.subTest(**over):
                r = self._signup(**over)
                self.assertEqual(r.status_code, 400, r.data)
                self.assertIn(field, str(r.data))


class BreakerFindingsTests(SimpleTestCase):
    databases = frozenset({'default'})

    def test_signup_refuses_a_number_stored_in_an_older_spelling(self):
        from rest_framework.test import APIClient

        from users.models import CustomUser
        u = CustomUser.objects.create_user(username='legacy', password='x', phone_number='+254711000501')
        CustomUser.objects.filter(pk=u.pk).update(phone_number='0711000501')
        r = APIClient().post('/api/users/register/', {
            'name': 'Amina Hassan', 'phone_number': '+254711000501',
            'password': 'StrongPassword123!', 'accept_terms': True}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(CustomUser.objects.filter(phone_number__endswith='711000501').count(), 1)

    def test_non_text_is_refused(self):
        from connect.validation import free_text, person_name, place
        for check in (place, person_name, free_text):
            for value in (True, 12, ['Westlands'], {'a': 1}):
                with self.subTest(check=check.__name__, value=value), self.assertRaises(ValidationError):
                    check(value)
