import re

from django.core.exceptions import ValidationError

# Mirrors the live checklist on the signup page (frontend PasswordChecklist).
RULES = (
    (r'[A-Z]', 'an uppercase letter'),
    (r'[a-z]', 'a lowercase letter'),
    (r'[0-9]', 'a number'),
    (r'[^A-Za-z0-9]', 'a special character (e.g. ! @ # -)'),
)


class PasswordComplexityValidator:
    def validate(self, password, user=None):
        missing = [label for pattern, label in RULES if not re.search(pattern, password)]
        if missing:
            raise ValidationError(
                'Password must contain ' + ', '.join(missing) + '.',
                code='password_too_simple',
            )

    def get_help_text(self):
        return 'Your password must contain an uppercase letter, a lowercase letter, a number and a special character.'
