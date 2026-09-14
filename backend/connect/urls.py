from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse

def home_view(request):
    return HttpResponse("Welcome to Connect API!")

urlpatterns = [
    path('', home_view),  # Handles the root URL so you don't get a 404
    path('admin/', admin.site.urls),
    path('api/users/', include('users.urls')),
    path('api/companies/', include('companies.urls')),
    path('api/bookings/', include('bookings.urls')),
    path('api/drivers/', include('drivers.urls')),
]