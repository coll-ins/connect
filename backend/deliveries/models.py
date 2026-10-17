import secrets

from django.conf import settings
from django.db import models

_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def generate_tracking_code():
    return 'PK' + ''.join(secrets.choice(_ALPHABET) for _ in range(8))


def generate_handover_pin():
    return f'{secrets.randbelow(1_000_000):06d}'


class Parcel(models.Model):
    SIZE_CHOICES = [('small', 'Small'), ('medium', 'Medium'), ('large', 'Large')]
    STATUS_CHOICES = [
        ('pending_payment', 'Pending payment'),
        ('paid', 'Paid'),
        ('picked_up', 'Picked up'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('failed_delivery', 'Failed delivery'),
        ('expired', 'Expired'),
    ]
    MAX_PIN_ATTEMPTS = 5

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='sent_parcels'
    )
    trip = models.ForeignKey(
        'companies.Trip', on_delete=models.PROTECT, related_name='parcels'
    )
    pickup_stage = models.ForeignKey(
        'companies.PickupStage', on_delete=models.PROTECT, related_name='parcels_picked_up_here'
    )
    dropoff_stage = models.ForeignKey(
        'companies.PickupStage', on_delete=models.PROTECT, related_name='parcels_dropped_here'
    )

    tracking_code = models.CharField(
        max_length=12, unique=True, default=generate_tracking_code, editable=False
    )
    handover_pin = models.CharField(
        max_length=6, default=generate_handover_pin, editable=False
    )
    pin_attempts = models.PositiveSmallIntegerField(default=0)

    description = models.CharField(max_length=200)
    size = models.CharField(max_length=10, choices=SIZE_CHOICES)
    receiver_name = models.CharField(max_length=100)
    receiver_phone = models.CharField(max_length=15)

    price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending_payment'
    )
    provider_reference = models.CharField(
        max_length=100, unique=True, null=True, blank=True
    )

    paid_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['sender', 'status']),
        ]

    def __str__(self):
        return f'{self.tracking_code} ({self.status})'
