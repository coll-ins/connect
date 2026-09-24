from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import CustomUser
from .serializers import UserSerializer


def normalize_phone_number(phone_number):
    digits = ''.join(character for character in (phone_number or '') if character.isdigit())
    if digits.startswith('254'):
        return f'+{digits}'
    if digits.startswith('0'):
        return f'+254{digits[1:]}'
    return f'+254{digits}' if digits else ''


def serialize_session_user(user):
    company = getattr(user, 'company', None)
    return {
        'id': user.id,
        'name': user.username,
        'username': user.username,
        'email': user.email,
        'phone': user.phone_number,
        'phone_number': user.phone_number,
        'location': user.location,
        'role': 'platform_admin' if user.is_superuser else user.role,
        'company_id': user.company_id,
        'company_name': company.name if company else None,
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
        'integrity_score': user.integrity_score,
    }


@ensure_csrf_cookie
def csrf_token(request):
    return JsonResponse({'csrfToken': get_token(request)})


@api_view(['POST'])
@permission_classes([AllowAny])
def signup(request):
    data = request.data.copy()
    data['phone_number'] = normalize_phone_number(data.get('phone_number'))

    if not data.get('phone_number') or not data.get('password'):
        return Response(
            {'error': 'Phone number and password are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    serializer = UserSerializer(data=data)
    if serializer.is_valid():
        user = serializer.save()
        login(request, user)
        return Response(
            {'message': 'Account created', 'user': serialize_session_user(user)},
            status=status.HTTP_201_CREATED,
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def admin_signup(request):
    admin_code = request.data.get('admin_code')
    if not admin_code or admin_code != getattr(settings, 'ADMIN_SIGNUP_CODE', None):
        return Response(
            {'error': 'Invalid or missing admin access code'},
            status=status.HTTP_403_FORBIDDEN,
        )

    data = request.data.copy()
    data['phone_number'] = normalize_phone_number(data.get('phone_number'))

    serializer = UserSerializer(data=data)
    if serializer.is_valid():
        with transaction.atomic():
            user = serializer.save()
            user.role = 'platform_admin'
            user.is_staff = True
            user.is_superuser = True
            user.save(update_fields=['role', 'is_staff', 'is_superuser'])
            login(request, user)

        return Response(
            {
                'message': 'Admin account created securely',
                'user': serialize_session_user(user),
            },
            status=status.HTTP_201_CREATED,
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def user_login(request):
    raw_phone = request.data.get('phone_number')
    password = request.data.get('password')

    if not raw_phone or not password:
        return Response(
            {'error': 'Phone number and password are required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    normalized_phone = normalize_phone_number(raw_phone)
    user_obj = CustomUser.objects.select_related('company').filter(
        phone_number__in=[normalized_phone, raw_phone]
    ).first()

    if user_obj is None:
        return Response(
            {'error': 'Wrong phone number or password'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    user = authenticate(request, username=user_obj.username, password=password)
    if user is None:
        return Response(
            {'error': 'Wrong phone number or password'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not user.is_active:
        return Response(
            {'error': 'Account is disabled'},
            status=status.HTTP_403_FORBIDDEN,
        )

    login(request, user)
    return Response(
        {'message': 'Login successful', 'user': serialize_session_user(user)},
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def user_logout(request):
    logout(request)
    return Response({'message': 'Logged out'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_profile(request):
    return Response(serialize_session_user(request.user))


@api_view(['GET'])
@permission_classes([AllowAny])
def user_api_root(request):
    return Response(
        {
            'message': 'CONNECT Users API',
            'endpoints': {
                'csrf': '/api/users/csrf/',
                'signup': '/api/users/signup/',
                'register': '/api/users/register/',
                'login': '/api/users/login/',
                'logout': '/api/users/logout/',
                'profile': '/api/users/profile/',
            },
        }
    )
