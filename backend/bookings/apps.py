from django.apps import AppConfig


class BookingsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bookings'

    def ready(self):
        from django.apps import apps
        from django.db.models.signals import post_save

        from . import live_signals

        driver_model = next(
            (m for m in apps.get_models() if m.__name__ == "Driver"), None
        )
        booking_model = apps.get_model("bookings", "Booking")

        if driver_model is not None:
            post_save.connect(
                live_signals.driver_saved,
                sender=driver_model,
                dispatch_uid="live_driver_saved",
            )

        post_save.connect(
            live_signals.booking_saved,
            sender=booking_model,
            dispatch_uid="live_booking_saved",
        )
