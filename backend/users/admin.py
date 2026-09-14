# User admin registration placeholder
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'phone_number', 'location', 'date_joined']
    search_fields = ['username', 'phone_number']
    fieldsets = UserAdmin.fieldsets + (
        ('Connect Info', {'fields': ('phone_number', 'location')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Connect Info', {'fields': ('phone_number', 'location')}),
    )