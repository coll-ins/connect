# users/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('passenger', 'Passenger'),
        ('driver', 'Driver'),
        ('company_manager', 'Company Manager'),
        ('company_auditor', 'Company Auditor'),
        ('company_operator', 'Company Operator'),
        ('platform_admin', 'Platform Admin'),
    ]

    phone_number = models.CharField(max_length=15, unique=True, blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='passenger')
    company = models.ForeignKey(
        'companies.Company', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='users'
    )
    boarded_count = models.PositiveIntegerField(default=0)
    no_show_count = models.PositiveIntegerField(default=0)

    REQUIRED_FIELDS = ['email', 'phone_number'] 


    @property
    def display_name(self):
        """Real name if set; phone number for auto-generated usernames;
        otherwise the username."""
        import re
        full = self.get_full_name().strip()
        if full:
            return full
        if re.fullmatch(r'(user|driver)_\+?\d+', self.username or ''):
            return self.phone_number or self.username
        return self.username

    @property
    def integrity_score(self):
        """
        Percentage of confirmed bookings actually boarded, out of
        boarded + no_show. Cancellations (either fault) never count
        here — only a real no-show does. Returns None until the
        user has at least one boarded-or-no-show event, so a brand
        new user isn't shown as either 0% or 100% with no history
        to back it up.
        """
        total = self.boarded_count + self.no_show_count
        if total == 0:
            return None
        return round((self.boarded_count / total) * 100, 1)

    def __str__(self):
        return f"{self.username} - {self.phone_number}"


# --- Phone numbers are stored in one canonical format (+254...) -----------------
from django.db.models.signals import pre_save  # noqa: E402

from .phone import canonical_phone  # noqa: E402


def _store_canonical_phone(sender, instance, **kwargs):
    if getattr(instance, 'phone_number', None):
        instance.phone_number = canonical_phone(instance.phone_number)


pre_save.connect(_store_canonical_phone, sender='users.CustomUser',
                 dispatch_uid='canonical_phone_user')
pre_save.connect(_store_canonical_phone, sender='drivers.Driver',
                 dispatch_uid='canonical_phone_driver')
