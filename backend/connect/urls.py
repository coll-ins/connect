from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView

urlpatterns = [
    path('', TemplateView.as_view(template_name='index.html')),  # Serves your frontend HTML template
    path('admin/', admin.site.urls),
    path('api/users/', include('users.urls')),
    path('api/companies/', include('companies.urls')),
    path('api/bookings/', include('bookings.urls')),
    path('api/drivers/', include('drivers.urls')),
]