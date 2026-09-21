from django.urls import path
from . import views

app_name = 'bookings'

urlpatterns = [
    path('create/', views.create_booking, name='create-booking'),
    path('my/', views.get_my_bookings, name='get-my-bookings'),
    path('all/', views.get_all_bookings, name='get-all-bookings'),
    path('<int:booking_id>/', views.get_booking_detail, name='get-booking-detail'),
    path('<int:booking_id>/assign-driver/', views.assign_driver, name='assign-driver'),
    path('<int:booking_id>/cancel/', views.cancel_booking, name='cancel-booking'),
    path('<int:booking_id>/verify-boarding/', views.verify_boarding, name='verify-boarding'),
    path('<int:booking_id>/location/', views.update_passenger_location, name='update-passenger-location'),
    path('<int:booking_id>/stage-departure/', views.set_stage_departure, name='set-stage-departure'),
    path('driver/<int:driver_id>/', views.get_driver_bookings, name='get-driver-bookings'),

    # Payment & webhook
    path('payments/<int:booking_id>/paystack/', views.initialize_paystack_payment, name='initialize-paystack-payment'),
    path('payments/<int:booking_id>/cash/', views.initialize_cash_payment, name='initialize-cash-payment'),
    path('payments/<int:booking_id>/cash/confirm/', views.confirm_cash_payment, name='confirm-cash-payment'),
    path('webhooks/paystack/', views.paystack_webhook, name='paystack-webhook'),
    path('webhooks/paystack/refund/', views.paystack_refund_webhook, name='paystack-refund-webhook'),
]