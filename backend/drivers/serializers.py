# Driver serializers placeholder
from rest_framework import serializers
from .models import Driver

class DriverSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True)

    class Meta:
        model = Driver
        fields = [
            'id', 'name', 'phone_number', 'bus_number', 'company', 'company_name',
            'is_available', 'latitude', 'longitude', 'location_updated_at',
        ]