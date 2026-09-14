# User URL routes placeholder
from django.urls import path
from . import views

urlpatterns = [
    path('csrf/', views.csrf_token, name='csrf-token'),
    path('signup/', views.signup, name='signup'),
    path('admin-signup/', views.admin_signup, name='admin-signup'),
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
]