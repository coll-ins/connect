from django.db import models
from companies.models import Company

class Driver(models.Model):
    name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=15)
    bus_number = models.CharField(max_length=20)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='drivers')
    is_available = models.BooleanField(default=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    location_updated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} - {self.bus_number}"


class LocationPing(models.Model):
    """One real GPS fix, kept for a short time to estimate road traffic."""

    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name='pings')
    latitude = models.FloatField()
    longitude = models.FloatField()
    recorded_at = models.DateTimeField(db_index=True)

    class Meta:
        indexes = [models.Index(fields=['driver', 'recorded_at'])]
