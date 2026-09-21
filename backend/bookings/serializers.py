from rest_framework import serializers
from companies.models import Trip
from drivers.models import Driver


class BookingCreateSerializer(serializers.Serializer):
    trip_id = serializers.IntegerField(required=True)
    seats = serializers.IntegerField(required=False, default=1, min_value=1)
    pickup_location = serializers.CharField(required=True, max_length=255)

    def validate_trip_id(self, value):
        if not Trip.objects.filter(id=value).exists():
            raise serializers.ValidationError("Trip does not exist.")
        return value


class AssignDriverSerializer(serializers.Serializer):
    driver_id = serializers.IntegerField(required=True)

    def validate_driver_id(self, value):
        if not Driver.objects.filter(id=value).exists():
            raise serializers.ValidationError("Driver does not exist.")
        return value


class PassengerLocationSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=True)