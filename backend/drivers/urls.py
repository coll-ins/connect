from django.urls import path
from . import views

urlpatterns = [
    path('', views.driver_list, name='driver-list'),
    path('<int:driver_id>/', views.driver_detail, name='driver-detail'),
    path('<int:driver_id>/location/', views.driver_location, name='driver-location'),
]