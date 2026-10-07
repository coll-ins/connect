from django.contrib import admin

from .models import Parcel


@admin.register(Parcel)
class ParcelAdmin(admin.ModelAdmin):
    list_display = ('tracking_code', 'status', 'price', 'sender', 'trip', 'created_at')
    list_filter = ('status',)
    search_fields = ('tracking_code', 'receiver_phone', 'sender__username')
    readonly_fields = ('tracking_code', 'handover_pin', 'provider_reference')
