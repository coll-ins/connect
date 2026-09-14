# Main URL router placeholder
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/users/', include('users.urls')),
    path('api/companies/', include('companies.urls')),
    path('api/bookings/', include('bookings.urls')),
    path('api/drivers/', include('drivers.urls')),
]