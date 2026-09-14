# Booking serializers placeholder
from django.utils import timezone
from rest_framework import serializers
from .models import Booking

class BookingSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True)
    user_phone = serializers.CharField(source='user.phone_number', read_only=True)
    route_name = serializers.CharField(source='route.name', read_only=True)
    company_name = serializers.CharField(source='route.company.name', read_only=True)
    driver_name = serializers.CharField(source='driver.name', read_only=True)
    driver_phone = serializers.CharField(source='driver.phone_number', read_only=True)
    driver_bus = serializers.CharField(source='driver.bus_number', read_only=True)
    driver_latitude = serializers.DecimalField(source='driver.latitude', max_digits=9, decimal_places=6, read_only=True)
    driver_longitude = serializers.DecimalField(source='driver.longitude', max_digits=9, decimal_places=6, read_only=True)
    stage_departure_minutes = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_number', 'status', 'pickup_location', 'seats', 'created_at',
            'user_name', 'user_phone', 'route_name', 'company_name',
            'driver_name', 'driver_phone', 'driver_bus', 'route', 'driver'
            , 'driver_latitude', 'driver_longitude', 'passenger_latitude', 'passenger_longitude',
            'stage_departure_at', 'stage_departure_minutes'
        ]

    def get_stage_departure_minutes(self, booking):
        if not booking.stage_departure_at:
            return None
        remaining = (booking.stage_departure_at - timezone.now()).total_seconds()
        return max(0, int((remaining + 59) // 60))