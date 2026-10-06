from django.urls import path

from . import views


app_name = 'drivers'


urlpatterns = [
    path(
        'me/',
        views.my_driver_profile,
        name='my-driver-profile',
    ),
    path(
        '',
        views.driver_list,
        name='driver-list',
    ),
    path(
        '<int:driver_id>/',
        views.driver_detail,
        name='driver-detail',
    ),
    path(
        '<int:driver_id>/location/',
        views.driver_location,
        name='driver-location',
    ),
]
