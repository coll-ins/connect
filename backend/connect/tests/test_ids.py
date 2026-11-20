from django.test import SimpleTestCase

from connect.ids import parse_id


class ParseIdTests(SimpleTestCase):
    def test_accepts_positive_ints_and_digit_strings(self):
        self.assertEqual(parse_id(5), 5)
        self.assertEqual(parse_id('5'), 5)
        self.assertEqual(parse_id(' 12 '), 12)
        self.assertEqual(parse_id(2 ** 63 - 1), 2 ** 63 - 1)

    def test_rejects_everything_that_cannot_be_a_database_id(self):
        for bad in (None, '', 'abc', '1e3', '-1', '1.5', 1.5, True, False, 0, -1, [1], {'a': 1},
                    2 ** 63, 10 ** 30, '9' * 40, '٣'):
            self.assertIsNone(parse_id(bad), repr(bad))
