# users/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    phone_number = models.CharField(max_length=15, unique=True, blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    company = models.ForeignKey(
        'companies.Company', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='users'
    )
    boarded_count = models.PositiveIntegerField(default=0)
    no_show_count = models.PositiveIntegerField(default=0)

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