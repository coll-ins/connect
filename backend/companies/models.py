from django.conf import settings
from django.db import models
from django.db.models import Q
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
    # Bus hire is opt-in: only companies that switch this on can receive requests.
    accepts_charters = models.BooleanField(default=False)

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
    via_points = models.JSONField(
        null=True,
        blank=True,
        default=list,
        help_text='Road points the manager placed to steer the line.',
    )

    # Parcel carriage is opt-in per route: a size with no rate is not carried.
    parcel_price_small = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    parcel_price_medium = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    parcel_price_large = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    def parcel_rate(self, size):
        return {
            'small': self.parcel_price_small,
            'medium': self.parcel_price_medium,
            'large': self.parcel_price_large,
        }.get(size)

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
    # The vehicle that runs this trip. Null only on trips made before trips
    # named a bus; every write path now requires one.
    bus = models.ForeignKey(
        "buses.Bus",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="trips",
    )
    # Seats for sale: always the bus's seat count when a bus is set.
    capacity = models.PositiveIntegerField()
    schedule = models.ForeignKey(
        "TripSchedule",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="trips",
    )

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

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "departure_at"],
                name="uniq_trip_per_schedule_slot",
            )
        ]

    def save(self, *args, **kwargs):
        if self.bus_id:
            self.capacity = self.bus.capacity
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.route.name} - {self.departure_at}"


class TripSchedule(models.Model):
    """A weekly service template expanded into Trips by generate_scheduled_trips."""
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="schedules")
    driver = models.ForeignKey("drivers.Driver", on_delete=models.CASCADE, related_name="trip_schedules")
    bus = models.ForeignKey(
        "buses.Bus", null=True, blank=True, on_delete=models.PROTECT, related_name="trip_schedules",
    )
    capacity = models.PositiveIntegerField(default=30)
    # Comma-separated weekdays, Monday=0 ... Sunday=6, e.g. "0,1,2,3,4"
    days_of_week = models.CharField(max_length=13)
    departure_time = models.TimeField()  # local time (Africa/Nairobi)
    service_end_time = models.TimeField(null=True, blank=True)
    normal_interval_minutes = models.PositiveSmallIntegerField(default=60)
    rush_interval_minutes = models.PositiveSmallIntegerField(default=30)
    rush_start_time = models.TimeField(null=True, blank=True)
    rush_end_time = models.TimeField(null=True, blank=True)
    auto_renew = models.BooleanField(default=False)
    generation_checked_at = models.DateTimeField(null=True, blank=True)
    driver_unavailable_count = models.PositiveIntegerField(default=0)
    driver_conflict_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.bus_id:
            self.capacity = self.bus.capacity
        super().save(*args, **kwargs)

    def weekdays(self):
        return {int(x) for x in self.days_of_week.split(",") if x.strip() != ""}

    def __str__(self):
        return f"{self.route.name} {self.departure_time} [{self.days_of_week}]"


class WeeklyOperationsReport(models.Model):
    REPORT_TYPE_CHOICES = [
        ('weekly', 'Weekly operations'),
        ('manual_renewal', 'Manual renewal reminder'),
    ]
    EMAIL_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('skipped', 'Skipped'),
        ('failed', 'Failed'),
    ]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='weekly_operations_reports',
    )
    report_type = models.CharField(max_length=20, choices=REPORT_TYPE_CHOICES)
    period_start = models.DateField()
    period_end = models.DateField()
    renewal_date = models.DateField(null=True, blank=True)
    summary = models.JSONField(default=dict)
    email_status = models.CharField(
        max_length=10,
        choices=EMAIL_STATUS_CHOICES,
        default='pending',
    )
    email_error = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    email_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'report_type', 'period_start'],
                name='uniq_company_operations_report_period',
            ),
        ]
        indexes = [
            models.Index(fields=['company', '-created_at']),
        ]


class TripSimulation(models.Model):
    """An admin-run walk of a trip's bus along its route, via the real GPS path."""
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('stopped', 'Stopped'),
        ('completed', 'Completed'),
        ('expired', 'Expired'),
    ]

    trip = models.ForeignKey(
        Trip, on_delete=models.CASCADE, related_name='simulations'
    )
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='trip_simulations',
    )
    path = models.JSONField()
    position_index = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='running'
    )
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['status'],
                condition=Q(status='running'),
                name='uniq_running_trip_simulation',
            ),
        ]
