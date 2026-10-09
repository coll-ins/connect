import datetime as dt
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from bookings.live_signals import location_freshness, trip_is_live, _payload
from drivers.models import Driver


class LocationFreshnessTests(SimpleTestCase):
    @override_settings(LOCATION_STALE_SECONDS=120)
    def test_recent_coordinates_are_fresh(self):
        driver = SimpleNamespace(
            latitude=-1.28,
            longitude=36.8,
            location_updated_at=timezone.now() - dt.timedelta(seconds=30),
        )
        result = location_freshness(driver)
        self.assertFalse(result["is_stale"])
        self.assertLessEqual(result["location_age_seconds"], 120)

    @override_settings(LOCATION_STALE_SECONDS=120)
    def test_two_day_old_location_is_stale(self):
        driver = SimpleNamespace(
            latitude=-1.28,
            longitude=36.8,
            location_updated_at=timezone.now() - dt.timedelta(days=2),
        )
        self.assertTrue(location_freshness(driver)["is_stale"])

    def test_missing_timestamp_is_stale(self):
        driver = SimpleNamespace(latitude=-1.28, longitude=36.8, location_updated_at=None)
        result = location_freshness(driver)
        self.assertTrue(result["is_stale"])
        self.assertIsNone(result["location_age_seconds"])

    def test_missing_coordinates_or_driver_is_stale(self):
        self.assertTrue(location_freshness(None)["is_stale"])
        driver = SimpleNamespace(latitude=None, longitude=36.8, location_updated_at=timezone.now())
        self.assertTrue(location_freshness(driver)["is_stale"])

    def test_driver_timestamp_is_not_automatically_refreshed_by_any_save(self):
        field = Driver._meta.get_field("location_updated_at")
        self.assertFalse(field.auto_now)
        self.assertTrue(field.null)

    def test_websocket_payload_includes_freshness_flag(self):
        now = timezone.now()
        driver = SimpleNamespace(latitude=-1.28, longitude=36.8, location_updated_at=now)
        booking = SimpleNamespace(id=42, passenger_latitude=-1.29, passenger_longitude=36.81)
        result = _payload(booking, driver)
        self.assertIn("is_stale", result)
        self.assertIn("location_age_seconds", result)
        self.assertIn("is_stale", result["driver"])

    def test_only_recent_boarding_or_departed_trip_is_live(self):
        now = timezone.now()
        recent = SimpleNamespace(status="departed", departure_at=now - dt.timedelta(hours=1))
        old = SimpleNamespace(status="departed", departure_at=now - dt.timedelta(hours=14))
        completed = SimpleNamespace(status="completed", departure_at=now - dt.timedelta(hours=1))
        self.assertTrue(trip_is_live(recent, now=now))
        self.assertFalse(trip_is_live(old, now=now))
        self.assertFalse(trip_is_live(completed, now=now))
