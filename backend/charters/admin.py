from django.contrib import admin

from .models import CharterRequest


@admin.register(CharterRequest)
class CharterRequestAdmin(admin.ModelAdmin):
    list_display = ('reference', 'status', 'company', 'passenger', 'depart_at', 'quote_price')
    list_filter = ('status', 'company')
    search_fields = ('reference', 'contact_phone', 'passenger__username')
    readonly_fields = ('reference', 'provider_reference')
