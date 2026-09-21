from django.urls import path
from . import views


urlpatterns = [
    path('', views.get_my_wallet, name='my-wallet'),
]
