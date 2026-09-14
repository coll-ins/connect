# Signup and login views placeholder
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.contrib.auth import authenticate, login, logout
from django.conf import settings
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from .serializers import UserSerializer
from .models import CustomUser


def normalize_phone_number(phone_number):
    digits = ''.join(character for character in (phone_number or '') if character.isdigit())
    if digits.startswith('254'):
        return f'+{digits}'
    if digits.startswith('0'):
        return f'+254{digits[1:]}'
    return f'+254{digits}' if digits else ''


@ensure_csrf_cookie
def csrf_token(request):
    return JsonResponse({'csrfToken': get_token(request)})

@api_view(['POST'])
def signup(request):
    data = request.data.copy()
    data['phone_number'] = normalize_phone_number(data.get('phone_number'))
    serializer = UserSerializer(data=data)
    if serializer.is_valid():
        user = serializer.save()
        login(request, user)
        return Response({
            'message': 'Account created',
            'user': {
                'id': user.id,
                'name': user.username,
                'phone': user.phone_number,
                'location': user.location
            }
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def admin_signup(request):
    if request.data.get('admin_code') != settings.ADMIN_SIGNUP_CODE:
        return Response({'error': 'Invalid admin access code'}, status=status.HTTP_403_FORBIDDEN)

    data = request.data.copy()
    data['phone_number'] = normalize_phone_number(data.get('phone_number'))
    serializer = UserSerializer(data=data)
    if serializer.is_valid():
        user = serializer.save()
        user.is_staff = True
        user.save(update_fields=['is_staff'])
        login(request, user)
        return Response({
            'message': 'Admin account created',
            'user': {
                'id': user.id,
                'name': user.username,
                'phone': user.phone_number,
                'location': user.location,
                'is_admin': True,
            },
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
def user_login(request):
    phone_number = normalize_phone_number(request.data.get('phone_number'))
    password = request.data.get('password')

    try:
        user_obj = CustomUser.objects.get(phone_number=phone_number)
        user = authenticate(request, username=user_obj.username, password=password)
        if user:
            login(request, user)
            return Response({
                'message': 'Login successful',
                'user': {
                    'id': user.id,
                    'name': user.username,
                    'phone': user.phone_number,
                    'location': user.location,
                    'is_admin': user.is_staff
                }
            })
    except CustomUser.DoesNotExist:
        pass

    return Response({'error': 'Wrong phone number or password'}, status=status.HTTP_401_UNAUTHORIZED)

@api_view(['POST'])
def user_logout(request):
    logout(request)
    return Response({'message': 'Logged out'})