import hmac
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import CsrfViewMiddleware, get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db import IntegrityError, transaction
from rest_framework import status
from django.contrib.auth.hashers import make_password
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.throttling import AnonRateThrottle
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import CustomUser
from .phone import canonical_phone, phone_variants
from .throttles import (
    LoginIPThrottle,
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


# The same body the serializer gives for an exact duplicate, so a phone that
# is taken never looks different from one spelled another way.
PHONE_TAKEN = {'phone_number': ['user with this phone number already exists.']}


def signup_phone(raw):
    """The canonical phone for a signup body value, or '' when it is not usable text."""
    if not isinstance(raw, str) or not raw.isascii():
        return ''
    canonical = canonical_phone(raw)
    return canonical if any(ch.isdigit() for ch in canonical) else ''


def is_claimable_walk_in(user):
    """A password-less passenger account made by a walk-in booking."""
    return (
        user.is_active
        and user.role == 'passenger'
        and not user.has_usable_password()
        and not user.is_superuser
        and not user.is_staff
        and user.company_id is None
    )


def claim_walk_in_account(request, data, phone):
    """Give the owner of a walk-in phone a password, keeping the booking history.

    Returns the claimed user, a Response when the body is invalid or the phone
    is not claimable, or None when no account has that phone.
    """
    with transaction.atomic():
        rows = list(
            CustomUser.objects.select_for_update()
            .filter(phone_number__in=phone_variants(phone))
        )
        if not rows:
            return None
        if len(rows) > 1 or not is_claimable_walk_in(rows[0]):
            return Response(PHONE_TAKEN, status=status.HTTP_400_BAD_REQUEST)
        user = rows[0]
        serializer = UserSerializer(data=data)
        serializer.fields['phone_number'].validators = [
            v for v in serializer.fields['phone_number'].validators
            if v.__class__.__name__ != 'UniqueValidator'
        ]
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        first, _, last = serializer.validated_data['name'].partition(' ')
        user.set_password(serializer.validated_data['password'])
        user.first_name, user.last_name = first, last
        user.save(update_fields=['password', 'first_name', 'last_name'])
        return user


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
    }


def csrf_refused(request):
    """A 403 Response unless the request carries a valid CSRF token and a trusted Origin.

    login and signup are AllowAny, so DRF's session authentication never runs
    its own CSRF check on them; a cross-site form could otherwise sign a
    victim's browser into an account chosen by the attacker.
    """
    check = CsrfViewMiddleware(lambda request: None)
    check.process_request(request._request)
    reason = check.process_view(request._request, None, (), {})
    if reason is None:
        return None
    return Response(
        {'error': 'CSRF check failed. Reload the page and try again.'},
        status=status.HTTP_403_FORBIDDEN,
    )


@ensure_csrf_cookie
def csrf_token(request):
    return JsonResponse({'csrfToken': get_token(request)})


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([SignupPhoneThrottle, AnonRateThrottle])
def signup(request):
    refused = csrf_refused(request)
    if refused is not None:
        return refused
    data = request.data.copy()
    data['phone_number'] = signup_phone(data.get('phone_number'))

    if not data.get('phone_number') or not data.get('password'):
        return Response(
            {'error': 'Phone number and password are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if len(str(data.get('password') or '')) < 8:
        return Response(
            {'error': 'Password must be at least 8 characters long.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    claimed = claim_walk_in_account(request, data, data['phone_number'])
    if isinstance(claimed, Response):
        return claimed
    if claimed is not None:
        login(request, claimed)
        return Response(
            {'message': 'Account created', 'user': serialize_session_user(claimed)},
            status=status.HTTP_201_CREATED,
        )

    serializer = UserSerializer(data=data)
    if serializer.is_valid():
        try:
            with transaction.atomic():
                user = serializer.save()
        except IntegrityError:
            return Response(PHONE_TAKEN, status=status.HTTP_400_BAD_REQUEST)
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
    data['phone_number'] = signup_phone(data.get('phone_number'))

    if data['phone_number'] and CustomUser.objects.filter(
            phone_number__in=phone_variants(data['phone_number'])).exists():
        return Response(PHONE_TAKEN, status=status.HTTP_400_BAD_REQUEST)

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
    refused = csrf_refused(request)
    if refused is not None:
        return refused
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
        try:
            company_id = int(requested_company_id)
        except (TypeError, ValueError):
            return Response(
                {'company': ['company must be a company id (a whole number).']},
                status=status.HTTP_400_BAD_REQUEST
            )
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
        if staff_user.pk == user.pk:
            return Response(
                {'error': 'You cannot remove your own account.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if staff_user.bookings.exists():
            # Deleting the user would cascade away their bookings and payments.
            staff_user.is_active = False
            staff_user.save(update_fields=['is_active'])
            return Response(
                {'message': 'Staff member deactivated. Their booking and '
                            'payment records are kept.'},
                status=status.HTTP_200_OK
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
