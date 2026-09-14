# Booking admin registration placeholder
from django.contrib import admin
from .models import Booking

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['booking_number', 'user', 'route', 'driver', 'status', 'created_at']
    list_filter = ['status', 'route__company']
    search_fields = ['booking_number', 'user__username', 'user__phone_number']
    readonly_fields = ['booking_number', 'created_at']