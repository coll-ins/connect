from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import TestCase


class PasswordComplexityTests(TestCase):
    def test_each_missing_rule_is_rejected(self):
        for weak in ('lowercase-only-1', 'UPPERCASE-ONLY-1', 'NoDigits-here', 'NoSpecial123'):
            with self.subTest(weak=weak), self.assertRaises(ValidationError):
                validate_password(weak)

    def test_complete_password_passes(self):
        validate_password('Tr4velSafe-2026')
