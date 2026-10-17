from django.urls import path

from . import views


app_name = 'buses'

urlpatterns = [
    path('', views.bus_list, name='bus-list'),
    path('<int:bus_id>/', views.bus_detail, name='bus-detail'),
]
