from django.urls import path
from . import views

app_name = 'users'

urlpatterns = [
    path('', views.user_api_root, name='user-api-root'),
    path('csrf/', views.csrf_token, name='csrf-token'),
    path('signup/', views.signup, name='signup'),
    path('register/', views.signup, name='register'),
    # path('admin-signup/', views.admin_signup, name='admin-signup'),
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('profile/', views.user_profile, name='profile'),
    path('user-profile/', views.user_profile, name='user_profile'),  # Added alias for test lookup
]