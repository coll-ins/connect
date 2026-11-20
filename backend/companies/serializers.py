from rest_framework import serializers
from users.phone import KENYA_MOBILE, canonical_phone

from .models import Company, Route, Trip, PickupStage


ROUTE_PRICE_MAX = 100000  # KES per seat; keeps price x seats inside the total_amount column


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = [
            'id',
            'name',
            'description',
            'areas_served',
            'phone_number',
        ]
        read_only_fields = ['id']

    def validate_phone_number(self, value):
        value = (value or '').strip()
        if not value:
            return value
        canonical = canonical_phone(value) if value.isascii() else value
        if not KENYA_MOBILE.match(canonical):
            raise serializers.ValidationError('Enter a Kenyan mobile number, e.g. 0712345678.')
        return canonical


class PickupStageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PickupStage
        fields = [
            'id',
            'route',
            'name',
            'latitude',
            'longitude',
            'order',
            'is_active',
            'source',
            'source_ref',
        ]
        read_only_fields = ['id', 'route']

    def validate_latitude(self, value):
        if not -90 <= value <= 90:
            raise serializers.ValidationError('Latitude must be between -90 and 90.')
        return value

    def validate_longitude(self, value):
        if not -180 <= value <= 180:
            raise serializers.ValidationError('Longitude must be between -180 and 180.')
        return value

    def validate_name(self, value):
        name = ' '.join(str(value).strip().split())

        if not name:
            raise serializers.ValidationError(
                'Pickup stage name is required.'
            )

        placeholder_names = {
            'unnamed',
            'unnamed bus stop',
            'unnamed stop',
            'unknown',
            'unknown stop',
            'bus stop',
            'stop',
        }

        if name.lower() in placeholder_names:
            raise serializers.ValidationError(
                'Please provide the actual pickup stage name.'
            )

        return name


class RouteSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source='company.name',
        read_only=True
    )

    via_points = serializers.JSONField(read_only=True)

    pickup_stages = PickupStageSerializer(
        many=True,
        read_only=True
    )

    class Meta:
        model = Route
        fields = [
            'id',
            'company',
            'company_name',
            'name',
            'start_point',
            'end_point',
            'price',
            'start_latitude',
            'start_longitude',
            'end_latitude',
            'end_longitude',
            'geometry',
            'via_points',
            'pickup_stages',
        ]
        read_only_fields = [
            'id',
            'company',
            'company_name',
            'pickup_stages',
        ]

    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError('Price must be greater than zero.')
        if value > ROUTE_PRICE_MAX:
            raise serializers.ValidationError(f'Price cannot be more than {ROUTE_PRICE_MAX}.')
        return value


class TripSerializer(serializers.ModelSerializer):
    route_details = RouteSerializer(source='route', read_only=True)

    driver_name = serializers.CharField(
        source='driver.name',
        read_only=True
    )

    driver_bus_number = serializers.CharField(
        source='driver.bus_number',
        read_only=True
    )

    company_name = serializers.CharField(
        source='route.company.name',
        read_only=True
    )

    booked_seats = serializers.SerializerMethodField()

    def get_booked_seats(self, obj):
        annotated = getattr(obj, 'booked_annot', None)
        if annotated is not None:
            return int(annotated)
        from bookings.services import seats_taken
        return seats_taken(obj)

    booking_closes_at = serializers.SerializerMethodField()
    booking_open = serializers.SerializerMethodField()
    seats_available = serializers.SerializerMethodField()

    def get_booking_closes_at(self, obj):
        from bookings.services import booking_closes_at
        return booking_closes_at(obj)

    def get_booking_open(self, obj):
        from django.utils import timezone
        return (
            obj.status in ('scheduled', 'boarding')
            and timezone.now() < self.get_booking_closes_at(obj)
        )

    def get_seats_available(self, obj):
        return max(obj.capacity - self.get_booked_seats(obj), 0)

    class Meta:
        model = Trip
        fields = [
            'id',
            'route',
            'route_details',
            'driver',
            'driver_name',
            'driver_bus_number',
            'company_name',
            'departure_at',
            'capacity',
            'status',
            'booked_seats',
            'booking_closes_at',
            'booking_open',
            'seats_available',
        ]
        read_only_fields = [
            'id',
            'driver_name',
            'driver_bus_number',
            'company_name',
        ]
