from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.http import JsonResponse
from companies.views import get_trips, get_trip_details

def health_check(request):
    return JsonResponse({'status': 'ok', 'service': 'CONNECT API'})


urlpatterns = [
    path('', TemplateView.as_view(template_name='index.html')),
    path('admin/', admin.site.urls),
    path('api/health/', health_check, name='health-check'),

    path('api/users/', include('users.urls')),
    path('api/companies/', include('companies.urls')),
    path('api/trips/', get_trips, name='get-trips'),
    path('api/trips/<int:trip_id>/', get_trip_details, name='get-trip-details'),
    path('api/bookings/', include('bookings.urls')),
    path('api/drivers/', include('drivers.urls')),
    path('api/wallet/', include('wallets.urls')),
]

admin.site.site_header = "My Custom API Admin"
admin.site.site_title = "Admin Portal"
admin.site.index_title = "Welcome to the Dashboard"