from rest_framework import serializers

from bookings.seats import OTHER, VEHICLES

from .models import Bus


class BusSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source='company.name',
        read_only=True,
    )
    vehicle_label = serializers.CharField(source='get_vehicle_type_display', read_only=True)
    plan_verified = serializers.SerializerMethodField()
    capacity = serializers.IntegerField(required=False)

    def get_plan_verified(self, obj):
        v = VEHICLES.get(obj.vehicle_type)
        return bool(v and v.get('verified', True))

    def validate(self, attrs):
        vehicle_type = attrs.get('vehicle_type', getattr(self.instance, 'vehicle_type', OTHER))
        if vehicle_type in VEHICLES:
            # The published plan decides the seat count, not the form.
            attrs['capacity'] = VEHICLES[vehicle_type]['seats']
        elif 'capacity' not in attrs and self.instance is None:
            raise serializers.ValidationError(
                {'capacity': 'Enter the number of passenger seats.'}
            )
        return attrs

    class Meta:
        model = Bus
        fields = [
            'id',
            'company',
            'company_name',
            'registration_number',
            'bus_number',
            'vehicle_type',
            'vehicle_label',
            'plan_verified',
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
