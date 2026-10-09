from django.test import SimpleTestCase

from bookings.models import generate_booking_number, generate_verification_pin


class GeneratorTests(SimpleTestCase):
    def test_pin_is_six_digits(self):
        for _ in range(200):
            self.assertRegex(generate_verification_pin(), r'^\d{6}$')

    def test_booking_number_shape_and_spread(self):
        numbers = {generate_booking_number() for _ in range(2000)}
        self.assertEqual(len(numbers), 2000)
        for n in numbers:
            self.assertRegex(n, r'^BK-[A-Z]{4}\d{6}$')
            self.assertLessEqual(len(n), 20)
