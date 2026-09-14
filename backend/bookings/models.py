# Booking model placeholder
from django.db import models
from users.models import CustomUser
from companies.models import Route
from drivers.models import Driver
import random
import string

def generate_booking_number():
    chars = ''.join(random.choices(string.ascii_uppercase, k=1))
    nums = ''.join(random.choices(string.digits, k=4))
    return f"C{chars}{nums}"

class Booking(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='bookings')
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name='bookings')
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True)
    booking_number = models.CharField(max_length=20, unique=True, default=generate_booking_number)
    pickup_location = models.CharField(max_length=255)
    seats = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    passenger_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    passenger_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    stage_departure_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.booking_number} - {self.user.username}"

    class Meta:
        ordering = ['-created_at']