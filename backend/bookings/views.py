# Booking, driver assignment, and SMS views placeholder
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.utils import timezone
from datetime import timedelta
from .models import Booking
from .serializers import BookingSerializer
from drivers.models import Driver
from notifications.sms import send_booking_sms, send_driver_sms

@api_view(['POST'])
def create_booking(request):
    user = request.user
    if not user.is_authenticated:
        return Response({'error': 'Login required'}, status=status.HTTP_401_UNAUTHORIZED)

    route_id = request.data.get('route_id')
    pickup_location = request.data.get('pickup_location')
    try:
        seats = int(request.data.get('seats', 1))
    except (TypeError, ValueError):
        return Response({'error': 'Number of seats must be a whole number'}, status=400)
    if seats < 1 or seats > 20:
        return Response({'error': 'Choose between 1 and 20 seats'}, status=400)
    if not route_id or not pickup_location:
        return Response({'error': 'Route and pickup location are required'}, status=400)

    booking = Booking.objects.create(
        user=user,
        route_id=route_id,
        pickup_location=pickup_location,
        seats=seats,
    )

    send_booking_sms(user.phone_number, booking.booking_number)

    serializer = BookingSerializer(booking)
    return Response({
        'message': 'Booking created',
        'booking': serializer.data
    }, status=status.HTTP_201_CREATED)

@api_view(['GET'])
def get_my_bookings(request):
    if not request.user.is_authenticated:
        return Response({'error': 'Login required'}, status=status.HTTP_401_UNAUTHORIZED)
    bookings = Booking.objects.filter(user=request.user)
    serializer = BookingSerializer(bookings, many=True)
    return Response(serializer.data)

@api_view(['GET'])
def get_all_bookings(request):
    if not request.user.is_staff:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    bookings = Booking.objects.all()
    company_id = request.query_params.get('company_id')
    if company_id:
        bookings = bookings.filter(route__company_id=company_id)
    serializer = BookingSerializer(bookings, many=True)
    return Response(serializer.data)

@api_view(['GET'])
def get_booking_detail(request, booking_id):
    if not request.user.is_staff:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    try:
        booking = Booking.objects.get(id=booking_id)
        serializer = BookingSerializer(booking)
        return Response(serializer.data)
    except Booking.DoesNotExist:
        return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
def assign_driver(request, booking_id):
    if not request.user.is_staff:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    try:
        booking = Booking.objects.get(id=booking_id)
        driver_id = request.data.get('driver_id')
        driver = Driver.objects.get(id=driver_id)

        if driver.company_id != booking.route.company_id:
            return Response({'error': 'Driver must belong to the booking company'}, status=400)

        booking.driver = driver
        booking.status = 'confirmed'
        booking.save()

        send_driver_sms(
            booking.user.phone_number,
            booking.booking_number,
            driver.name,
            driver.phone_number,
            driver.bus_number
        )

        serializer = BookingSerializer(booking)
        return Response({'message': 'Driver assigned', 'booking': serializer.data})
    except Booking.DoesNotExist:
        return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
    except Driver.DoesNotExist:
        return Response({'error': 'Driver not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
def complete_booking(request, booking_id):
    if not request.user.is_authenticated:
        return Response({'error': 'Login required'}, status=status.HTTP_401_UNAUTHORIZED)
    try:
        booking = Booking.objects.get(id=booking_id)
    except Booking.DoesNotExist:
        return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
    if booking.user_id != request.user.id:
        return Response({'error': 'Only the passenger can complete this trip'}, status=status.HTTP_403_FORBIDDEN)
    if booking.status != 'confirmed':
        return Response({'error': 'Only a confirmed trip can be completed'}, status=status.HTTP_400_BAD_REQUEST)
    booking.status = 'completed'
    booking.save(update_fields=['status'])
    return Response({'message': 'Trip completed', 'booking': BookingSerializer(booking).data})


@api_view(['POST'])
def update_passenger_location(request, booking_id):
    if not request.user.is_authenticated:
        return Response({'error': 'Login required'}, status=status.HTTP_401_UNAUTHORIZED)
    try:
        booking = Booking.objects.get(id=booking_id, user=request.user)
    except Booking.DoesNotExist:
        return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
    if booking.status != 'confirmed':
        return Response({'error': 'Only a confirmed trip can share location'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        latitude = float(request.data['latitude'])
        longitude = float(request.data['longitude'])
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return Response({'error': 'Valid latitude and longitude are required'}, status=status.HTTP_400_BAD_REQUEST)
    booking.passenger_latitude = latitude
    booking.passenger_longitude = longitude
    booking.save(update_fields=['passenger_latitude', 'passenger_longitude'])
    return Response(BookingSerializer(booking).data)


@api_view(['GET'])
def get_driver_bookings(request, driver_id):
    bookings = Booking.objects.filter(
        driver_id=driver_id,
        status='confirmed',
    ).select_related('user', 'route', 'route__company', 'driver')
    return Response(BookingSerializer(bookings, many=True).data)


@api_view(['POST'])
def set_stage_departure(request, booking_id):
    if not request.user.is_staff:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    try:
        minutes = int(request.data.get('minutes'))
    except (TypeError, ValueError):
        return Response({'error': 'Enter a whole number of minutes'}, status=status.HTTP_400_BAD_REQUEST)
    if minutes < 0 or minutes > 240:
        return Response({'error': 'Minutes must be between 0 and 240'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        booking = Booking.objects.get(id=booking_id)
    except Booking.DoesNotExist:
        return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
    booking.stage_departure_at = timezone.now() + timedelta(minutes=minutes)
    booking.save(update_fields=['stage_departure_at'])
    return Response(BookingSerializer(booking).data)