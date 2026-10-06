from rest_framework import serializers
from .models import Company, Route, Trip, PickupStage


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
            'pickup_stages',
        ]
        read_only_fields = [
            'id',
            'company',
            'company_name',
            'pickup_stages',
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
