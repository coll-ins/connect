# Company and route views placeholder
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .models import Company, Route
from .serializers import CompanySerializer, RouteSerializer

@api_view(['GET'])
def get_companies(request):
    location = request.query_params.get('location', '')
    if location:
        companies = Company.objects.filter(areas_served__icontains=location)
        if not companies.exists():
            companies = Company.objects.all()
    else:
        companies = Company.objects.all()
    serializer = CompanySerializer(companies, many=True)
    return Response(serializer.data)

@api_view(['GET'])
def get_routes(request, company_id):
    try:
        routes = Route.objects.filter(company_id=company_id)
        serializer = RouteSerializer(routes, many=True)
        return Response(serializer.data)
    except Exception:
        return Response({'error': 'Company not found'}, status=status.HTTP_404_NOT_FOUND)