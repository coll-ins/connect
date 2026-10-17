from rest_framework import serializers

from .models import Bus


class BusSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source='company.name',
        read_only=True,
    )

    class Meta:
        model = Bus
        fields = [
            'id',
            'company',
            'company_name',
            'registration_number',
            'bus_number',
            'capacity',
            'is_active',
            'is_available',
            'maintenance_status',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'company',
            'company_name',
            'created_at',
            'updated_at',
        ]

    def validate_capacity(self, value):
        if value < 1:
            raise serializers.ValidationError(
                'Bus capacity must be at least 1.'
            )

        if value > 100:
            raise serializers.ValidationError(
                'Bus capacity cannot exceed 100.'
            )

        return value

    def validate_registration_number(self, value):
        value = value.strip().upper()

        if not value:
            raise serializers.ValidationError(
                'Registration number is required.'
            )

        return value

    def validate_bus_number(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                'Bus number is required.'
            )

        return value
