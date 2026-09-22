from rest_framework import serializers
from .models import Company, Route, Trip


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = '__all__'


class RouteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Route
        fields = [
            'id',
            'company',
            'name',
            'start_point',
            'end_point',
            'price',
        ]


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
        ]
        read_only_fields = [
            'id',
            'driver_name',
            'driver_bus_number',
            'company_name',
        ]