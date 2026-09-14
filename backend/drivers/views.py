# Driver views placeholder
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.utils import timezone
from .models import Driver
from .serializers import DriverSerializer
from companies.models import Company

@api_view(['GET'])
def get_drivers(request):
    company_id = request.query_params.get('company_id')
    if company_id and company_id.lower() != 'null':
        drivers = Driver.objects.filter(company_id=company_id, is_available=True)
    else:
        drivers = Driver.objects.filter(is_available=True)
    serializer = DriverSerializer(drivers, many=True)
    return Response(serializer.data)


@api_view(['POST'])
def create_driver(request):
    if not request.user.is_staff:
        return Response({'error': 'Unauthorized'}, status=403)
    required = ['name', 'phone_number', 'bus_number', 'company']
    if any(not request.data.get(field) for field in required):
        return Response({'error': 'Name, phone, bus number, and company are required'}, status=400)
    try:
        company = Company.objects.get(id=request.data['company'])
    except Company.DoesNotExist:
        return Response({'error': 'Company not found'}, status=404)
    driver = Driver.objects.create(
        name=request.data['name'].strip(),
        phone_number=request.data['phone_number'].strip(),
        bus_number=request.data['bus_number'].strip(),
        company=company,
    )
    return Response(DriverSerializer(driver).data, status=201)


@api_view(['POST'])
def update_driver_location(request, driver_id):
    try:
        driver = Driver.objects.get(id=driver_id)
        driver.latitude = request.data.get('latitude')
        driver.longitude = request.data.get('longitude')
        driver.location_updated_at = timezone.now()
        driver.save(update_fields=['latitude', 'longitude', 'location_updated_at'])
        return Response(DriverSerializer(driver).data)
    except Driver.DoesNotExist:
        return Response({'error': 'Driver not found'}, status=404)