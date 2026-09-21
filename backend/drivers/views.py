from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status


@api_view(['GET'])
def driver_list(request):
    """List all drivers."""
    # Replace with your actual queryset/serializer logic when ready
    return Response([], status=status.HTTP_200_OK)


@api_view(['GET'])
def driver_detail(request, driver_id):
    """Retrieve driver details by ID."""
    return Response({"id": driver_id}, status=status.HTTP_200_OK)


@api_view(['GET'])
def driver_location(request, driver_id):
    """Retrieve driver location by ID."""
    return Response({"driver_id": driver_id, "latitude": 0.0, "longitude": 0.0}, status=status.HTTP_200_OK)