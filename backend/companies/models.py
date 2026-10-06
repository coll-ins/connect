from django.db import models
from users.models import CustomUser


class Company(models.Model):
    user = models.OneToOneField(
        CustomUser, 
        on_delete=models.CASCADE, 
        related_name='owned_company',  # <-- Changed from 'company'
        null=True, 
        blank=True
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    areas_served = models.TextField()
    phone_number = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Companies'


class Route(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='routes')
    name = models.CharField(max_length=200)
    start_point = models.CharField(max_length=100)
    end_point = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    # Map data. These are nullable so existing routes remain valid
    # until their real coordinates and road geometry are configured.
    start_latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    start_longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    end_latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    end_longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    geometry = models.JSONField(
        null=True,
        blank=True,
        help_text='Road-following route geometry as GeoJSON.',
    )

    def __str__(self):
        return f"{self.company.name} - {self.name}"


class PickupStage(models.Model):
    route = models.ForeignKey(
        Route,
        on_delete=models.CASCADE,
        related_name='pickup_stages',
    )
    name = models.CharField(max_length=150)
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
    )
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    source = models.CharField(
        max_length=20,
        choices=[
            ('automatic', 'Automatic'),
            ('manual', 'Manual'),
        ],
        default='manual',
    )
    source_ref = models.CharField(
        max_length=100,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['order', 'id']
        indexes = [
            models.Index(fields=['route', 'is_active']),
        ]

    def __str__(self):
        return f"{self.route.name} - {self.name}"


class Trip(models.Model):
    route = models.ForeignKey(
        Route,
        on_delete=models.CASCADE,
        related_name="trips"
    )
    driver = models.ForeignKey(
        "drivers.Driver",
        on_delete=models.CASCADE,
        related_name="trips"
    )
    departure_at = models.DateTimeField()
    capacity = models.PositiveIntegerField()

    STATUS_CHOICES = [
        ("scheduled", "Scheduled"),
        ("boarding", "Boarding"),
        ("departed", "Departed"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="scheduled",
    )

    def __str__(self):
        return f"{self.route.name} - {self.departure_at}"