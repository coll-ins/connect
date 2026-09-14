# Company and route URL routes placeholder
from django.urls import path
from . import views

urlpatterns = [
    path('', views.get_companies, name='companies'),
    path('<int:company_id>/routes/', views.get_routes, name='routes'),
]