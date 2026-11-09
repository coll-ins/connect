import hmac
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db import transaction
from rest_framework import status
from django.contrib.auth.hashers import make_password
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import CustomUser
from .phone import canonical_phone, phone_variants
from .throttles import (
    LoginIPThrottle,
    SignupIPThrottle,
    SignupPhoneThrottle,
    clear_login_failures,
    login_blocked,
    record_login_failure,
)
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


def session_role(user):
    """Platform admin is is_superuser and nothing else: a stored
    'platform_admin' role without superuser grants nothing, so it must not
    open the admin screens either."""
    if user.is_superuser:
        return 'platform_admin'
    if user.role == 'platform_admin':
        return 'passenger'
    return user.role


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
        'role': session_role(user),
        'company_id': user.company_id,
        'company_name': company.name if company else None,
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
        'integrity_score': user.integrity_score,
        'can_pay_cash': user.can_pay_cash,
        'cash_enabled': settings.CASH_ENABLED,
        'trips_counted': user.boarded_count + user.no_show_count,
    }


@ensure_csrf_cookie
def csrf_token(request):
    return JsonResponse({'csrfToken': get_token(request)})


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([SignupPhoneThrottle, SignupIPThrottle, AnonRateThrottle])
def signup(request):
    data = request.data.copy()
    data['phone_number'] = canonical_phone(data.get('phone_number')) or ''

    if not data.get('phone_number') or not data.get('password'):
        return Response(
            {'error': 'Phone number and password are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Older rows may hold 07... or 2547...; one number, one account.
    if CustomUser.objects.filter(phone_number__in=phone_variants(data['phone_number'])).exists():
        return Response(
            {'error': 'This phone number already has an account. Sign in instead.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if len(str(data.get('password') or '')) < 8:
        return Response(
            {'error': 'Password must be at least 8 characters long.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if str(data.get('accept_terms')).lower() not in ('true', '1', 'on'):
        return Response(
            {'error': 'Accept the Terms of Service and Privacy Policy to create an account.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    serializer = UserSerializer(data=data)
    if serializer.is_valid():
        user = serializer.save()
        user.terms_version = settings.TERMS_VERSION
        user.terms_accepted_at = timezone.now()
        user.save(update_fields=['terms_version', 'terms_accepted_at'])
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
    data['phone_number'] = canonical_phone(data.get('phone_number')) or ''

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
@throttle_classes([LoginIPThrottle])
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

    client_ip = LoginIPThrottle().get_ident(request)
    if login_blocked(raw_phone, client_ip):
        return Response(
            {'error': 'Too many failed attempts. Try again in an hour.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    user_obj = (
        CustomUser.objects
        .select_related('company')
        .filter(phone_number__in=phone_variants(raw_phone))
        .first()
    )

    if user_obj is None:
        # Spend the same hashing time as a real check so response timing
        # does not reveal which phone numbers are registered.
        make_password(password)
        user = None
    else:
        user = authenticate(
            request,
            username=user_obj.username,
            password=password,
        )

    if user is None:
        record_login_failure(raw_phone, client_ip)
        return Response(
            {'error': 'Invalid phone number or password.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    clear_login_failures(raw_phone)

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
    # The platform-admin Users screen reads the directory from this URL.
    if request.user.is_authenticated and request.user.is_superuser:
        users = CustomUser.objects.select_related('company').order_by('id')
        return Response([
            {
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'phone_number': u.phone_number,
                'role': session_role(u),
                'company': u.company_id,
                'company_name': u.company.name if u.company else None,
                'is_active': u.is_active,
            }
            for u in users
        ])
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

        # Managers are peers: one must not reset another's password or
        # remove them and take the company over.
        if staff_user.role == 'company_manager' and staff_user.pk != user.pk:
            return Response(
                {'error': 'Another manager can only be changed by the platform admin.'},
                status=status.HTTP_403_FORBIDDEN
            )

    if request.method == 'DELETE':
        if staff_user.pk == user.pk:
            return Response(
                {'error': 'You cannot remove your own account.'},
                status=status.HTTP_400_BAD_REQUEST
            )
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

    new_phone = serializer.validated_data.get('phone_number')
    if new_phone and CustomUser.objects.filter(
        phone_number__in=phone_variants(new_phone)
    ).exclude(pk=staff_user.pk).exists():
        return Response(
            {'error': 'A user with this phone number already exists.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    requested_role = serializer.validated_data.get('role')

    if staff_user.pk == user.pk and (
        'role' in serializer.validated_data
        or 'is_active' in serializer.validated_data
    ):
        return Response(
            {'error': 'You cannot change your own role or active status.'},
            status=status.HTTP_400_BAD_REQUEST
        )

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

        try:
            validate_password(password, staff_user)
        except DjangoValidationError as exc:
            return Response(
                {'error': ' '.join(exc.messages)},
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


class DeleteAccountThrottle(UserRateThrottle):
    # Stops password guessing from a session left open on a shared phone.
    rate = '5/hour'


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([DeleteAccountThrottle])
def delete_account(request):
    """Close a passenger's own account. Bookings, payments and parcels stay
    for the companies' books, so the row is anonymised, not deleted."""
    user = request.user
    if user.role != 'passenger' or user.is_superuser:
        return Response(
            {'error': 'Staff and driver accounts are closed by your company manager.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    if not user.check_password(request.data.get('password') or ''):
        return Response(
            {'error': 'That password is wrong. Enter the password you sign in with.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    from bookings.models import Booking
    from charters.models import CharterRequest
    from deliveries.models import Parcel
    from wallets.models import Wallet

    with transaction.atomic():
        user = CustomUser.objects.select_for_update().get(pk=user.pk)
        wallet = Wallet.objects.select_for_update().filter(user=user).first()
        blockers = []
        if wallet and (wallet.available_balance > 0 or wallet.held_balance > 0):
            blockers.append(
                f'you still have KES {wallet.available_balance + wallet.held_balance:,.0f} '
                'in your wallet. Withdraw or use it first'
            )
        if Booking.objects.filter(user=user, status__in=['pending', 'confirmed']).exists():
            blockers.append('you have a booking that is not finished. Cancel it or complete the trip first')
        if Parcel.objects.filter(sender=user, status__in=['pending_payment', 'paid', 'picked_up']).exists():
            blockers.append('you have a parcel on its way. Wait until it is delivered or cancel it first')
        if CharterRequest.objects.filter(
            passenger=user, status__in=['requested', 'quoted', 'confirmed'],
        ).exists():
            blockers.append('you have an open bus hire. Cancel it or wait until it is completed first')
        if blockers:
            return Response(
                {'error': 'We cannot close your account yet: ' + '; '.join(blockers) + '.'},
                status=status.HTTP_409_CONFLICT,
            )

        user.username = f'deleted_{user.pk}'
        user.first_name = ''
        user.last_name = ''
        user.email = ''
        user.phone_number = None
        user.location = None
        user.is_active = False
        user.set_unusable_password()
        user.save()

    logout(request)
    return Response({'message': 'Your account is closed and your personal details are removed.'})
