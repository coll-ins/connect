from django.contrib import admin
from .models import Booking, Payment, BoardingEvent


class PaymentInline(admin.StackedInline):
    model = Payment
    extra = 0
    readonly_fields = ('created_at', 'confirmed_at')
    can_delete = False


class BoardingEventInline(admin.StackedInline):
    model = BoardingEvent
    extra = 0
    readonly_fields = ('verified_at',)
    can_delete = False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        'booking_number',
        'user',
        'route',
        'trip',
        'driver',
        'seats',
        'total_amount',
        'status',
        'verification_pin',
        'created_at',
    )
    list_filter = ('status', 'created_at', 'route')
    search_fields = (
        'booking_number',
        'user__username',
        'user__email',
        'user__phone_number',
        'pickup_location',
        'verification_pin',
    )
    readonly_fields = ('booking_number', 'created_at', 'updated_at')
    inlines = [PaymentInline, BoardingEventInline]
    ordering = ('-created_at',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'booking',
        'amount',
        'method',
        'status',
        'provider_reference',
        'created_at',
    )
    list_filter = ('status', 'method', 'created_at')
    search_fields = (
        'booking__booking_number',
        'booking__user__username',
        'provider_reference',
        'idempotency_key',
    )
    readonly_fields = ('created_at', 'confirmed_at')
    ordering = ('-created_at',)


@admin.register(BoardingEvent)
class BoardingEventAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'booking',
        'trip',
        'method',
        'verified_by',
        'verified_at',
    )
    list_filter = ('method', 'verified_at')
    search_fields = (
        'booking__booking_number',
        'booking__user__username',
        'verified_by__username',
    )
    readonly_fields = ('verified_at',)
    ordering = ('-verified_at',)