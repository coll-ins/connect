from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView

urlpatterns = [
    path('', TemplateView.as_view(template_name='index.html')),
    path('admin/', admin.site.urls),

    path('api/users/', include('users.urls')),
    path('api/companies/', include('companies.urls')),
    path('api/bookings/', include('bookings.urls')),
    path('api/drivers/', include('drivers.urls')),
    path('api/wallet/', include('wallets.urls')),
]

# Customizing the default Django Admin interface text
admin.site.site_header = "My Custom API Admin"        # Top banner & login page title
admin.site.site_title = "Admin Portal"                # Browser tab title
admin.site.index_title = "Welcome to the Dashboard"    # Homepage subtitle
