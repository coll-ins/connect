from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from companies.models import Company
from users.permissions import can_manage_company

from .models import Bus
from .serializers import BusSerializer


COMPANY_STAFF_ROLES = {
    'company_manager',
    'company_auditor',
    'company_operator',
}


def _can_view_company_buses(user):
    """
    Company staff can view buses belonging to their company.
    Superusers can view all buses.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return (
        user.role in COMPANY_STAFF_ROLES
        and user.company_id is not None
    )


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def bus_list(request):
    """
    List or create buses.

    GET:
        Company staff can view buses belonging to their company.
        Superusers can view buses across all companies.

    POST:
        Only Company Managers and superusers can create buses.
    """
    user = request.user

    if request.method == 'GET':
        if not _can_view_company_buses(user):
            return Response(
                {'error': 'You are not authorized to view buses.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        queryset = Bus.objects.select_related('company')

        requested_company_id = request.query_params.get('company_id')

        if user.is_superuser:
            if requested_company_id:
                queryset = queryset.filter(
                    company_id=requested_company_id
                )
        else:
            if requested_company_id and str(
                requested_company_id
            ) != str(user.company_id):
                return Response(
                    {
                        'error':
                        'You cannot access buses from another company.'
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            queryset = queryset.filter(
                company_id=user.company_id
            )

        queryset = queryset.order_by('company_id', 'bus_number')

        return Response(
            BusSerializer(queryset, many=True).data,
            status=status.HTTP_200_OK,
        )

    requested_company_id = request.data.get('company')

    if user.is_superuser:
        if not requested_company_id:
            return Response(
                {'error': 'company is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        company_id = requested_company_id

    else:
        if not can_manage_company(user):
            return Response(
                {
                    'error':
                    'Only a Company Manager can add buses.'
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        company_id = user.company_id

        if requested_company_id and str(
            requested_company_id
        ) != str(company_id):
            return Response(
                {
                    'error':
                    'You cannot create buses for another company.'
                },
                status=status.HTTP_403_FORBIDDEN,
            )

    company = get_object_or_404(
        Company,
        id=company_id,
    )

    serializer = BusSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

    bus = serializer.save(company=company)

    return Response(
        BusSerializer(bus).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'PATCH', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def bus_detail(request, bus_id):
    """
    Retrieve, update or delete one bus.

    Company Managers can modify buses belonging to their company.
    Auditors and Operators are read-only.
    Superusers can modify any bus.
    """
    bus = get_object_or_404(
        Bus.objects.select_related('company'),
        id=bus_id,
    )

    user = request.user

    if not user.is_superuser:
        if user.role not in COMPANY_STAFF_ROLES:
            return Response(
                {'error': 'You are not authorized to access buses.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if user.company_id is None:
            return Response(
                {'error': 'Company assignment required.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if bus.company_id != user.company_id:
            return Response(
                {
                    'error':
                    'You cannot access buses from another company.'
                },
                status=status.HTTP_403_FORBIDDEN,
            )

    if request.method == 'GET':
        return Response(
            BusSerializer(bus).data,
            status=status.HTTP_200_OK,
        )

    if not can_manage_company(user, bus.company):
        return Response(
            {
                'error':
                'Only a Company Manager can modify buses.'
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == 'DELETE':
        bus.delete()

        return Response(
            {'message': 'Bus removed successfully.'},
            status=status.HTTP_200_OK,
        )

    serializer = BusSerializer(
        bus,
        data=request.data,
        partial=request.method == 'PATCH',
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

    serializer.save()

    return Response(
        BusSerializer(bus).data,
        status=status.HTTP_200_OK,
    )
