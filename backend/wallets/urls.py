from django.urls import path
from . import views


urlpatterns = [
    path('', views.get_my_wallet, name='my-wallet'),
    path('topup/', views.start_topup, name='wallet-topup'),
    path('topup/<str:reference>/', views.topup_status, name='wallet-topup-status'),
    path('withdraw/', views.withdraw, name='wallet-withdraw'),
    path('withdrawals/', views.my_withdrawals, name='wallet-withdrawals'),
    path('transactions/', views.my_transactions, name='wallet-transactions'),
]
