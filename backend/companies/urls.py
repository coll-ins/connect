from django.urls import path
from . import views

urlpatterns = [
    path('', views.get_companies, name='get_companies'),
    path('routes/', views.get_routes, name='get_routes'),
    path('<int:company_id>/routes/', views.get_routes, name='get_company_routes'),
    path('trips/', views.get_trips, name='get_trips'),
    path('<int:company_id>/trips/', views.get_trips, name='get_company_trips'),
    path('trips/<int:trip_id>/', views.get_trip_details, name='get_trip_details'),
    path('trips/<int:trip_id>/status/', views.update_trip_status, name='update_trip_status'),
    path('<int:company_id>/analytics/', views.company_analytics, name='company_analytics'),
]
