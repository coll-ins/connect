# Driver URL routes placeholder
from django.urls import path
from . import views

urlpatterns = [
    path('', views.get_drivers, name='drivers'),
    path('create/', views.create_driver, name='create-driver'),
    path('<int:driver_id>/location/', views.update_driver_location, name='driver-location'),
]