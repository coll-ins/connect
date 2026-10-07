from django.urls import path

from . import views

app_name = 'charters'

urlpatterns = [
    path('', views.charter_list_create, name='charter-list-create'),
    path('companies/', views.charter_companies, name='charter-companies'),
    path('company/', views.charter_company, name='charter-company'),
    path('driver/', views.driver_charters, name='charter-driver'),
    path('<int:charter_id>/', views.charter_detail, name='charter-detail'),
    path('<int:charter_id>/quote/', views.charter_quote, name='charter-quote'),
    path('<int:charter_id>/decline/', views.charter_decline, name='charter-decline'),
    path('<int:charter_id>/cancel/', views.charter_cancel, name='charter-cancel'),
    path('<int:charter_id>/pay/', views.charter_pay, name='charter-pay'),
    path('<int:charter_id>/verify/', views.charter_verify, name='charter-verify'),
    path('<int:charter_id>/complete/', views.charter_complete, name='charter-complete'),
]
