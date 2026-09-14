# Booking URL routes placeholder
from django.urls import path
from . import views

urlpatterns = [
    path('create/', views.create_booking, name='create-booking'),
    path('mine/', views.get_my_bookings, name='my-bookings'),
    path('all/', views.get_all_bookings, name='all-bookings'),
    path('<int:booking_id>/', views.get_booking_detail, name='booking-detail'),
    path('<int:booking_id>/assign-driver/', views.assign_driver, name='assign-driver'),
    path('<int:booking_id>/complete/', views.complete_booking, name='complete-booking'),
    path('<int:booking_id>/passenger-location/', views.update_passenger_location, name='passenger-location'),
    path('<int:booking_id>/stage-departure/', views.set_stage_departure, name='stage-departure'),
    path('driver/<int:driver_id>/active/', views.get_driver_bookings, name='driver-bookings'),
]