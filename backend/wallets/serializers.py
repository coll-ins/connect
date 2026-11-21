from rest_framework import serializers
from .models import Wallet, WalletTransaction


class WalletSerializer(serializers.ModelSerializer):
    total_balance = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = [
            'available_balance',
            'held_balance',
            'total_balance',
        ]

    def get_total_balance(self, wallet):
        return wallet.available_balance + wallet.held_balance


class WalletTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletTransaction
        fields = ['id', 'type', 'amount', 'balance_after', 'reference', 'booking', 'created_at']
