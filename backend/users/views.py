import hmac
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.throttling import AnonRateThrottle
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import CustomUser
from .throttles import LoginPhoneThrottle
from .serializers import UserSerializer, CompanyStaffSerializer
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError


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
        'name': user.display_name,
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
    if not getattr(settings, 'ALLOW_ADMIN_SIGNUP', False):
        return Response({'error': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    admin_code = request.data.get('admin_code')
    if not admin_code or not hmac.compare_digest(
        str(admin_code).encode(),
        str(getattr(settings, 'ADMIN_SIGNUP_CODE', '') or '').encode()):
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
@throttle_classes([LoginPhoneThrottle, AnonRateThrottle])
def user_login(request):
    raw_phone = request.data.get('phone_number')
    password = request.data.get('password')

    if not raw_phone or not password:
        return Response(
            {
                'error': 'Phone number and password are required.'
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    normalized_phone = normalize_phone_number(raw_phone)

    user_obj = (
        CustomUser.objects
        .select_related('company')
        .filter(
            phone_number__in=[normalized_phone, str(raw_phone).strip()]
        )
        .first()
    )

    if user_obj is None:
        return Response(
            {'error': 'Invalid phone number or password.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    user = authenticate(
        request,
        username=user_obj.username,
        password=password,
    )

    if user is None:
        return Response(
            {'error': 'Invalid phone number or password.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not user.is_active:
        return Response(
            {'error': 'Account is disabled.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    login(request, user)

    return Response(
        {
            'message': 'Login successful',
            'user': serialize_session_user(user),
        },
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


COMPANY_STAFF_ROLES = {
    'company_manager',
    'company_auditor',
    'company_operator',
}


def _can_manage_staff(user):
    """Only company managers and platform superusers can manage staff."""
    return (
        user.is_authenticated
        and (
            user.is_superuser
            or (
                user.role == 'company_manager'
                and user.company_id is not None
            )
        )
    )


def _can_view_staff(user):
    """Company staff can view their own company's staff."""
    return (
        user.is_authenticated
        and (
            user.is_superuser
            or (
                user.role in COMPANY_STAFF_ROLES
                and user.company_id is not None
            )
        )
    )


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def company_staff(request):
    """
    List or create company staff.

    GET:
        Managers, auditors and operators can view staff in their company.
        Superusers can view staff across all companies.

    POST:
        Only managers and superusers can create staff.
    """
    user = request.user

    if request.method == 'GET':
        if not _can_view_staff(user):
            return Response(
                {'error': 'You are not authorized to view company staff.'},
                status=status.HTTP_403_FORBIDDEN
            )

        queryset = CustomUser.objects.select_related('company').filter(
            role__in=COMPANY_STAFF_ROLES
        )

        if not user.is_superuser:
            queryset = queryset.filter(company_id=user.company_id)

        queryset = queryset.order_by('id')

        return Response(
            CompanyStaffSerializer(queryset, many=True).data,
            status=status.HTTP_200_OK
        )

    if not _can_manage_staff(user):
        return Response(
            {'error': 'Only a Company Manager can manage company staff.'},
            status=status.HTTP_403_FORBIDDEN
        )

    requested_company_id = request.data.get('company')

    if user.is_superuser:
        if not requested_company_id:
            return Response(
                {'error': 'company is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        company_id = requested_company_id
    else:
        company_id = user.company_id

        if (
            requested_company_id
            and str(requested_company_id) != str(company_id)
        ):
            return Response(
                {'error': 'You cannot create staff for another company.'},
                status=status.HTTP_403_FORBIDDEN
            )

    from companies.models import Company

    try:
        company = Company.objects.get(id=company_id)
    except Company.DoesNotExist:
        return Response(
            {'error': 'Company not found.'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = CompanyStaffSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    role = serializer.validated_data.get('role')

    if role not in COMPANY_STAFF_ROLES:
        return Response(
            {'error': 'Invalid company staff role.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    password = request.data.get('password')

    if not password:
        return Response(
            {'error': 'password is required when creating staff.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        validate_password(password)
    except DjangoValidationError as exc:
        return Response(
            {'error': ' '.join(exc.messages)},
            status=status.HTTP_400_BAD_REQUEST
        )

    username = serializer.validated_data.get('username', '').strip()

    if not username:
        username = serializer.validated_data.get('phone_number', '').replace(
            '+', 'user_'
        )

    if CustomUser.objects.filter(username=username).exists():
        return Response(
            {'error': 'A user with this username already exists.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    from users.phone import phone_variants

    if CustomUser.objects.filter(
        phone_number__in=phone_variants(
            serializer.validated_data.get('phone_number')
        )
    ).exists():
        return Response(
            {'error': 'A user with this phone number already exists.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    with transaction.atomic():
        staff_user = CustomUser.objects.create_user(
            username=username,
            email=serializer.validated_data.get('email', ''),
            phone_number=serializer.validated_data.get('phone_number'),
            location=serializer.validated_data.get('location', ''),
            password=password,
        )
        staff_user.role = role
        staff_user.company = company
        staff_user.is_staff = False
        staff_user.is_superuser = False
        staff_user.save(
            update_fields=[
                'role',
                'company',
                'is_staff',
                'is_superuser',
            ]
        )

    return Response(
        CompanyStaffSerializer(staff_user).data,
        status=status.HTTP_201_CREATED
    )


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def company_staff_detail(request, staff_id):
    """
    Update or remove a company staff member.

    Managers can modify staff in their own company.
    Superusers can modify staff globally.
    Auditors and operators are read-only.
    """
    user = request.user

    try:
        staff_user = CustomUser.objects.select_related('company').get(
            id=staff_id
        )
    except CustomUser.DoesNotExist:
        return Response(
            {'error': 'Staff member not found.'},
            status=status.HTTP_404_NOT_FOUND
        )

    if staff_user.is_superuser:
        return Response(
            {'error': 'Superusers cannot be managed through company staff.'},
            status=status.HTTP_403_FORBIDDEN
        )

    if staff_user.role not in COMPANY_STAFF_ROLES:
        return Response(
            {'error': 'This user is not a company staff member.'},
            status=status.HTTP_403_FORBIDDEN
        )

    if not user.is_superuser:
        if user.role != 'company_manager':
            return Response(
                {'error': 'Only a Company Manager can manage staff.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if user.company_id is None:
            return Response(
                {'error': 'Company assignment required.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if staff_user.company_id != user.company_id:
            return Response(
                {'error': 'You cannot manage staff from another company.'},
                status=status.HTTP_403_FORBIDDEN
            )

    if request.method == 'DELETE':
        staff_user.delete()

        return Response(
            {'message': 'Staff member removed successfully.'},
            status=status.HTTP_200_OK
        )

    serializer = CompanyStaffSerializer(
        staff_user,
        data=request.data,
        partial=True
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    requested_role = serializer.validated_data.get('role')

    if requested_role is not None and requested_role not in COMPANY_STAFF_ROLES:
        return Response(
            {'error': 'Invalid company staff role.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if 'password' in request.data:
        password = request.data.get('password')

        if not password:
            return Response(
                {'error': 'password cannot be empty.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(password) < 6:
            return Response(
                {'error': 'password must be at least 6 characters.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        staff_user.set_password(password)

    with transaction.atomic():
        serializer.save()

        if 'password' in request.data:
            staff_user.save(update_fields=['password'])

    return Response(
        CompanyStaffSerializer(staff_user).data,
        status=status.HTTP_200_OK
    )
