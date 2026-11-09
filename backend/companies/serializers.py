from rest_framework import serializers
from connect.validation import free_text, kenyan_mobile, place

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

    def validate_name(self, value):
        return place(value, 'the company name', example='e.g. Super Metro Sacco')

    def validate_description(self, value):
        return free_text(value, 'the company description', required=False)

    def validate_areas_served(self, value):
        return place(value, 'the areas served', max_length=500,
                     example='e.g. CBD, Westlands, Rongai')

    def validate_phone_number(self, value):
        return kenyan_mobile(value) if str(value or '').strip() else ''


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

        return place(name, 'the pickup stage name', example='e.g. Kencom or Odeon')


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

    def validate_name(self, value):
        return place(value, 'the route name', max_length=200,
                     example='e.g. CBD to Rongai via Lang\'ata')

    def validate_start_point(self, value):
        return place(value, 'the starting point', example='e.g. Kencom, CBD')

    def validate_end_point(self, value):
        return place(value, 'the end point', example='e.g. Rongai')


class TripSerializer(serializers.ModelSerializer):
    route_details = RouteSerializer(source='route', read_only=True)

    driver_name = serializers.CharField(
        source='driver.name',
        read_only=True
    )

    # The trip's own bus when it has one; older trips fall back to the
    # number typed on the driver.
    driver_bus_number = serializers.SerializerMethodField()
    bus_plate = serializers.CharField(source='bus.registration_number', read_only=True, default=None)
    vehicle_label = serializers.SerializerMethodField()

    def get_driver_bus_number(self, obj):
        return obj.bus.bus_number if obj.bus_id else obj.driver.bus_number

    def get_vehicle_label(self, obj):
        return obj.bus.get_vehicle_type_display() if obj.bus_id else None

    company_name = serializers.CharField(
        source='route.company.name',
        read_only=True
    )

    booked_seats = serializers.SerializerMethodField()

    def get_booked_seats(self, obj):
        annotated = getattr(obj, 'booked_annot', None)
        if annotated is not None:
            return int(annotated) + int(getattr(obj, 'blocked_annot', 0) or 0)
        from bookings.seats import seats_taken
        return seats_taken(obj)

    class Meta:
        model = Trip
        fields = [
            'id',
            'route',
            'route_details',
            'driver',
            'driver_name',
            'driver_bus_number',
            'bus',
            'bus_plate',
            'vehicle_label',
            'company_name',
            'departure_at',
            'capacity',
            'status',
            'booked_seats',
        ]
        read_only_fields = [
            'id',
            'driver_name',
            'driver_bus_number',
            'bus',
            'bus_plate',
            'vehicle_label',
            'capacity',
            'company_name',
        ]
