# Company and route serializers placeholder
from rest_framework import serializers
from .models import Company, Route

class RouteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Route
        fields = ['id', 'name', 'start_point', 'end_point', 'price']

class CompanySerializer(serializers.ModelSerializer):
    routes = RouteSerializer(many=True, read_only=True)

    class Meta:
        model = Company
        fields = ['id', 'name', 'description', 'areas_served', 'phone_number', 'routes']