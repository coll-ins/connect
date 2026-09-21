import random
import string
from django.db import models
from users.models import CustomUser
from companies.models import Route, Trip
from drivers.models import Driver


def generate_booking_number():
    chars = ''.join(random.choices(string.ascii_uppercase, k=2))
    nums = ''.join(random.choices(string.digits, k=5))
    return f"BK-{chars}{nums}"


def generate_verification_pin():
    return ''.join(random.choices(string.digits, k=4))


class Booking(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show'),
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='bookings')
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name='bookings')
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_bookings')
    trip = models.ForeignKey(Trip, on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings')
    
    booking_number = models.CharField(max_length=20, unique=True, default=generate_booking_number, editable=False)
    verification_pin = models.CharField(max_length=6, default=generate_verification_pin)
    
    pickup_location = models.CharField(max_length=255)
    seats = models.PositiveIntegerField(default=1)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    passenger_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    passenger_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    stage_departure_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.booking_number} | {self.user.username} ({self.status})"

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['booking_number']),
            models.Index(fields=['status']),
        ]


class Payment(models.Model):
    METHOD_CHOICES = [
        ('digital', 'Digital (M-Pesa/Card)'),
        ('cash', 'Cash'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]

    SETTLEMENT_STATUS_CHOICES = [
        ('not_ready', 'Not Ready'),
        ('eligible', 'Eligible'),
        ('settled', 'Settled'),
        ('refunded', 'Refunded'),
    ]

    booking = models.OneToOneField(
        Booking,
        on_delete=models.CASCADE,
        related_name='payment'
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    method = models.CharField(
        max_length=10,
        choices=METHOD_CHOICES
    )

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='pending'
    )

    settlement_status = models.CharField(
        max_length=20,
        choices=SETTLEMENT_STATUS_CHOICES,
        default='not_ready'
    )

    provider_reference = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True
    )

    idempotency_key = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True
    )

    confirmed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    settled_at = models.DateTimeField(
        null=True,
        blank=True
    )

    refunded_at = models.DateTimeField(
        null=True,
        blank=True
    )
    refund_amount = models.DecimalField(
    max_digits=10,
    decimal_places=2,
    null=True,
    blank=True,
    )

    refund_reference = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )

    refund_status = models.CharField(
        max_length=20,
        choices=[
            ('not_requested', 'Not Requested'),
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('processed', 'Processed'),
            ('failed', 'Failed'),
        ],
        default='not_requested',
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return (
            f"Payment {self.booking.booking_number} - "
            f"{self.amount} ({self.status}/{self.settlement_status})"
        )
    

class BoardingEvent(models.Model):
    METHOD_CHOICES = [
        ('qr', 'QR Scan'),
        ('pin', 'PIN Entry'),
    ]

    booking = models.OneToOneField(
        Booking,
        on_delete=models.CASCADE,
        related_name='boarding_event'
    )
    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name='boarding_events'
    )
    method = models.CharField(max_length=3, choices=METHOD_CHOICES)
    verified_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_boardings'
    )
    verified_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Boarded: {self.booking.booking_number} via {self.method.upper()}"