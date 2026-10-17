from django.test import SimpleTestCase

from users.phone import phone_variants


class PhoneVariantsTests(SimpleTestCase):
    def test_every_kenyan_spelling_is_covered(self):
        for raw in ('0712345678', '+254712345678', '254712345678'):
            self.assertEqual(
                phone_variants(raw),
                {'0712345678', '+254712345678', '254712345678'},
                raw,
            )

    def test_blank_has_no_variants(self):
        for blank in (None, '', '   '):
            self.assertEqual(phone_variants(blank), set())

    def test_foreign_number_is_not_rewritten(self):
        self.assertEqual(phone_variants('+14155552671'), {'+14155552671'})
