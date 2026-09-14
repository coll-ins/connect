# Driver admin registration placeholder
from django.contrib import admin
from .models import Driver

@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ['name', 'phone_number', 'bus_number', 'company', 'is_available']
    list_filter = ['company', 'is_available']
    search_fields = ['name', 'phone_number', 'bus_number']