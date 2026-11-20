# Create your models here.
from django.db import models
from users.models import CustomUser


class Wallet(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='wallet')
    available_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    held_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(available_balance__gte=0) & models.Q(held_balance__gte=0),
                name='wallet_nonnegative',
            ),
        ]

    def __str__(self):
        return f"{self.user.username} - available: {self.available_balance}, held: {self.held_balance}"


class WalletTransaction(models.Model):
    TYPE_CHOICES = [
        ('deposit', 'Deposit'),
        ('hold', 'Hold'),
        ('release', 'Release'),
        ('refund', 'Refund'),
        ('credit', 'Credit'),
        ('adjustment', 'Adjustment'),
        ('spend', 'Spend'),
        ('withdrawal', 'Withdrawal'),
        ('withdrawal_reversal', 'Withdrawal reversal'),
    ]

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wallet_transactions',
    )
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    # Signed delta: credits positive, debits negative. SUM(amount) == Wallet.available_balance.
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    balance_after = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # Unique, so a movement (e.g. 'topup:<paystack ref>') can only ever be applied once.
    reference = models.CharField(max_length=100, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=~models.Q(amount=0), name='wallettx_amount_nonzero'),
        ]

    def __str__(self):
        return f"{self.type} {self.amount} - {self.wallet.user.username}"

class WalletTopUp(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('credited', 'Credited'),
        ('review', 'Review'),
        ('expired', 'Expired'),
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='wallet_topups')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    credited_at = models.DateTimeField(null=True, blank=True)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='wallettopup_amount_positive'),
        ]

    def __str__(self):
        return f"{self.reference} {self.status} {self.amount}"


class WalletPayout(models.Model):
    """One withdrawal to the account's own M-Pesa number. Not bookings.Payout (company payouts)."""
    STATUS_CHOICES = [
        ('requested', 'Requested'),
        ('submitted', 'Submitted'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('review', 'Review'),
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='wallet_payouts')
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='payouts')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    destination_phone = models.CharField(max_length=20)
    idempotency_key = models.CharField(max_length=64)
    reference = models.CharField(max_length=60, unique=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='requested')
    gateway_transfer_code = models.CharField(max_length=100, blank=True, default='')
    attempts = models.PositiveSmallIntegerField(default=0)
    failure_reason = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'idempotency_key'], name='walletpayout_user_key_unique'),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='walletpayout_amount_positive'),
        ]

    def __str__(self):
        return f"payout {self.pk} {self.status} {self.amount}"


class WalletPayoutEvent(models.Model):
    """Audit trail: one row per status change of a payout."""
    payout = models.ForeignKey(WalletPayout, on_delete=models.CASCADE, related_name='events')
    from_status = models.CharField(max_length=10, blank=True, default='')
    to_status = models.CharField(max_length=10)
    note = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
