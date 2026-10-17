import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
DEFAULT_DURATION = timedelta(hours=12)


def generate_reference():
    return 'CH' + ''.join(secrets.choice(_ALPHABET) for _ in range(8))


class CharterRequest(models.Model):
    STATUS_CHOICES = [
        ('requested', 'Requested'),
        ('quoted', 'Quoted'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('declined', 'Declined'),
        ('cancelled', 'Cancelled'),
    ]

    passenger = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='charter_requests')
    company = models.ForeignKey(
        'companies.Company', on_delete=models.PROTECT, related_name='charter_requests')
    driver = models.ForeignKey(
        'drivers.Driver', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='charters')

    reference = models.CharField(
        max_length=12, unique=True, default=generate_reference, editable=False)
    purpose = models.CharField(max_length=200)
    pickup_location = models.CharField(max_length=255)
    destination = models.CharField(max_length=255)
    depart_at = models.DateTimeField()
    return_at = models.DateTimeField(null=True, blank=True)
    passenger_count = models.PositiveIntegerField()
    contact_name = models.CharField(max_length=100)
    contact_phone = models.CharField(max_length=15)
    notes = models.TextField(blank=True)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='requested')
    quote_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    quote_valid_until = models.DateTimeField(null=True, blank=True)
    decline_reason = models.CharField(max_length=300, blank=True)
    provider_reference = models.CharField(max_length=100, unique=True, null=True, blank=True)

    paid_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['company', 'status']),
            models.Index(fields=['driver', 'status']),
        ]

    def end_at(self):
        return self.return_at or (self.depart_at + DEFAULT_DURATION)

    def effective_status(self):
        if (self.status == 'quoted' and self.quote_valid_until
                and self.quote_valid_until <= timezone.now()):
            return 'expired'
        return self.status

    def __str__(self):
        return f'{self.reference} ({self.status})'
