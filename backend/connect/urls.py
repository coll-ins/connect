from connect import cron as cron_views

from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from companies.views import get_trips, get_trip_details
from connect.system_checks import run_system_checks
from connect.demo_simulation import (
    advance_demo_simulation,
    demo_simulation_collection,
    stop_demo_simulation,
)

def health_check(request):
    return JsonResponse({'status': 'ok', 'service': 'CONNECT API'})

def system_diagnostics(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {'detail': 'Authentication required.'},
            status=401
        )

    if not request.user.is_superuser:
        return JsonResponse(
            {'detail': 'Platform administrator access required.'},
            status=403
        )

    return JsonResponse(
        run_system_checks(),
        status=200
    )


urlpatterns = [
    path('', health_check, name='root'),
    path('admin/', admin.site.urls),
    path('api/health/', health_check, name='health-check'),
    path(
    'api/system/diagnostics/',
    system_diagnostics,
    name='system-diagnostics'
),
    path(
        'api/system/demo-simulation/',
        demo_simulation_collection,
        name='demo-simulation',
    ),
    path(
        'api/system/demo-simulation/<int:simulation_id>/advance/',
        advance_demo_simulation,
        name='advance-demo-simulation',
    ),
    path(
        'api/system/demo-simulation/<int:simulation_id>/stop/',
        stop_demo_simulation,
        name='stop-demo-simulation',
    ),

    path('api/users/', include('users.urls')),
    path('api/companies/', include('companies.urls')),
    path('api/trips/', get_trips, name='get-trips'),
    path('api/trips/<int:trip_id>/', get_trip_details, name='get-trip-details'),
    path('api/bookings/', include('bookings.urls')),
    path('api/drivers/', include('drivers.urls')),
    path('api/buses/', include('buses.urls')),
    path('api/wallet/', include('wallets.urls')),
    path('api/deliveries/', include('deliveries.urls')),
    path('api/internal/cron/<slug:job>/', cron_views.run_job, name='cron-job'),
    path('api/charters/', include('charters.urls')),
]

admin.site.site_header = "My Custom API Admin"
admin.site.site_title = "Admin Portal"
admin.site.index_title = "Welcome to the Dashboard"