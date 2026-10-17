# Create your models here.
from django.db import models
from users.models import CustomUser


class Wallet(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='wallet')
    available_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    held_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

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
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.type} {self.amount} - {self.wallet.user.username}"