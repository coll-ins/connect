from django.test import SimpleTestCase
from rest_framework import serializers

from buses.serializers import BusSerializer


class PlateTests(SimpleTestCase):
    def test_kenyan_plates_are_stored_in_one_form(self):
        check = BusSerializer().validate_registration_number
        for raw, stored in (('KDK 404M', 'KDK 404M'), ('kdk404m', 'KDK 404M'),
                            (' kca  123 a ', 'KCA 123A'), ('EVA 001A', 'EVA 001A')):
            self.assertEqual(check(raw), stored)

    def test_anything_else_is_refused(self):
        check = BusSerializer().validate_registration_number
        for raw in ('', 'asdf', 'KDK 40M', 'ABC 123D', 'KDK 4040M', 'KDK404', 'bus one'):
            with self.subTest(raw=raw), self.assertRaises(serializers.ValidationError):
                check(raw)
