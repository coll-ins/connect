from django.urls import path

from . import views

app_name = 'deliveries'

urlpatterns = [
    path('', views.parcel_list_create, name='parcel-list-create'),
    path('quote/', views.parcel_quote, name='parcel-quote'),
    path('driver/', views.driver_parcels, name='driver-parcels'),
    path('company/', views.company_parcels, name='company-parcels'),
    path('options/', views.parcel_options, name='parcel-options'),
    path('rates/', views.route_rates, name='route-rates'),
    path('rates/<int:route_id>/', views.route_rates_update, name='route-rates-update'),
    path('<int:parcel_id>/', views.parcel_detail, name='parcel-detail'),
    path('<int:parcel_id>/cancel/', views.parcel_cancel, name='parcel-cancel'),
    path('<int:parcel_id>/pay/', views.parcel_pay, name='parcel-pay'),
    path('<int:parcel_id>/verify/', views.parcel_verify, name='parcel-verify'),
    path('<int:parcel_id>/pickup/', views.parcel_pickup, name='parcel-pickup'),
    path('<int:parcel_id>/deliver/', views.parcel_deliver, name='parcel-deliver'),
]
