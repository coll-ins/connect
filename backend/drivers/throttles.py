from rest_framework.throttling import UserRateThrottle


class DriverLocationThrottle(UserRateThrottle):
    """Own bucket for GPS pushes so they don't drain the shared user quota."""
    scope = 'driver_location'
