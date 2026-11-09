from django.db import models

from bookings.seats import OTHER, VEHICLES

from companies.models import Company


class Bus(models.Model):
    MAINTENANCE_STATUS_CHOICES = [
        ('operational', 'Operational'),
        ('maintenance', 'Under Maintenance'),
        ('out_of_service', 'Out of Service'),
    ]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='buses',
    )
    registration_number = models.CharField(
        max_length=20,
        unique=True,
    )
    bus_number = models.CharField(
        max_length=20,
    )
    VEHICLE_TYPE_CHOICES = [(k, v['label']) for k, v in VEHICLES.items()] + [
        (OTHER, 'Other (enter the seat count)'),
    ]
    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_TYPE_CHOICES, default=OTHER)
    # Passenger seats. Fixed by vehicle_type except for 'other'.
    capacity = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    is_available = models.BooleanField(default=True)
    maintenance_status = models.CharField(
        max_length=20,
        choices=MAINTENANCE_STATUS_CHOICES,
        default='operational',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['company_id', 'bus_number']
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'bus_number'],
                name='unique_bus_number_per_company',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.vehicle_type in VEHICLES:
            self.capacity = VEHICLES[self.vehicle_type]['seats']
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.company.name} - {self.bus_number} ({self.registration_number})"
