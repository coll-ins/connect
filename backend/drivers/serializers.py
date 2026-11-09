# Driver serializers placeholder
from rest_framework import serializers
from connect.validation import kenyan_mobile, person_name

from .models import Driver

class DriverSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True)

    class Meta:
        model = Driver
        fields = [
            'id', 'name', 'phone_number', 'bus_number', 'company', 'company_name',
            'is_available', 'latitude', 'longitude', 'location_updated_at',
        ]

    def validate_name(self, value):
        return person_name(value, "the driver's name")

    def validate_phone_number(self, value):
        return kenyan_mobile(value)
