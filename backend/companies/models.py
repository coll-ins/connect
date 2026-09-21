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

    def __str__(self):
        return f"{self.company.name} - {self.name}"


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