import secrets
import string
from django.db import models
from users.models import CustomUser
from companies.models import Route, Trip
from drivers.models import Driver


def generate_booking_number():
    chars = ''.join(secrets.choice(string.ascii_uppercase) for _ in range(4))
    nums = ''.join(secrets.choice(string.digits) for _ in range(6))
    return f"BK-{chars}{nums}"


def generate_verification_pin():
    return ''.join(secrets.choice(string.digits) for _ in range(6))


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

    # New structured pickup point. Nullable so existing bookings continue
    # working while the system is migrated to recognized pickup stages.
    pickup_stage = models.ForeignKey(
        'companies.PickupStage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bookings',
    )

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
    refund_claimed_at = models.DateTimeField(null=True, blank=True)
    payout = models.ForeignKey(
        'bookings.Payout',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='payments',
    )
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


class Incident(models.Model):
    INCIDENT_TYPE_CHOICES = [
        ('breakdown', 'Breakdown'),
        ('accident', 'Accident'),
        ('road_blocked', 'Road Blocked'),
        ('stage_issue', 'Stage Issue'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('reported', 'Reported'),
        ('investigating', 'Investigating'),
        ('resolved', 'Resolved'),
        ('cancelled', 'Cancelled'),
    ]

    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name='incidents',
    )

    reported_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reported_incidents',
    )

    incident_type = models.CharField(
        max_length=30,
        choices=INCIDENT_TYPE_CHOICES,
    )

    description = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='reported',
    )

    reported_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return (
            f"{self.get_incident_type_display()} - "
            f"{self.trip.route.name}"
        )

    class Meta:
        ordering = ['-reported_at']
        indexes = [
            models.Index(fields=['trip', 'status']),
            models.Index(fields=['reported_at']),
        ]


class BookingHold(models.Model):
    STATUS_CHOICES = [
        ('held', 'Held'),
        ('released', 'Released'),
        ('refunded', 'Refunded'),
        ('transferred', 'Transferred'),
        ('cancelled', 'Cancelled'),
    ]

    booking = models.OneToOneField(
        Booking,
        on_delete=models.CASCADE,
        related_name='financial_hold',
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    refunded_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='held',
    )

    held_at = models.DateTimeField(
        auto_now_add=True,
    )

    released_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    refunded_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    transferred_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return (
            f"{self.booking.booking_number} - "
            f"{self.amount} - {self.status}"
        )

class IncidentResolution(models.Model):
    RESOLUTION_CHOICES = [
        ('refund', 'Refund'),
        ('reschedule', 'Reschedule'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    booking = models.OneToOneField(
        Booking,
        on_delete=models.CASCADE,
        related_name='incident_resolution',
    )

    incident = models.ForeignKey(
        Incident,
        on_delete=models.CASCADE,
        related_name='resolutions',
    )

    resolution = models.CharField(
        max_length=20,
        choices=RESOLUTION_CHOICES,
    )

    replacement_trip = models.ForeignKey(
        Trip,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='incident_rescheduled_bookings',
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
    )

    refund_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return (
            f"{self.booking.booking_number} - "
            f"{self.resolution} ({self.status})"
        )


class Payout(models.Model):
    """One manual payout (M-Pesa or bank) to a company, covering a batch of payments."""

    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.PROTECT,
        related_name='payouts',
    )
    reference = models.CharField(max_length=100, unique=True)
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    fee_per_seat = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    fee_amount = models.DecimalField(max_digits=12, decimal_places=2)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2)
    payments_count = models.PositiveIntegerField()
    breakdown = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Payout {self.reference} to {self.company_id}: {self.net_amount}'


class UnappliedPayment(models.Model):
    """A successful Paystack charge for a parcel or bus hire that could not be applied."""

    STATUS_CHOICES = [
        ('retry', 'Retry'),
        ('refund_due', 'Refund due'),
        ('refunding', 'Refund claimed'),
        ('refunded', 'Refund sent'),
        ('review', 'Needs review'),
        ('applied', 'Applied'),
    ]

    reference = models.CharField(max_length=100, unique=True)
    kind = models.CharField(max_length=10)
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=10, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='retry')
    attempts = models.PositiveSmallIntegerField(default=0)
    refund_status = models.CharField(max_length=20, blank=True)
    refund_reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.reference} [{self.status}]'


class PayoutItem(models.Model):
    """One non-seat item (a completed charter) paid out inside a Payout."""

    payout = models.ForeignKey(Payout, on_delete=models.PROTECT, related_name='items')
    kind = models.CharField(max_length=10)
    object_id = models.PositiveBigIntegerField()
    reference = models.CharField(max_length=100, blank=True)
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    fee_amount = models.DecimalField(max_digits=12, decimal_places=2)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['kind', 'object_id'], name='uniq_payout_item'),
        ]

    def __str__(self):
        return f'{self.kind} {self.object_id} in payout {self.payout_id}'
