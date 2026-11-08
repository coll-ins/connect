import math
import time
from unittest import mock
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver, LocationPing
from drivers.traffic import _Line, _route_coords, compute_traffic
from drivers.views import record_driver_fix

LAT = -1.29
LNG0 = 36.80
DEG_PER_M = 1 / (111194.9 * math.cos(math.radians(LAT)))
# Straight east-west road, about 2.2 km long.
COORDS = [[LNG0, LAT], [LNG0 + 2200 * DEG_PER_M, LAT]]
T0 = timezone.now() - timedelta(minutes=10)


def drive(driver_id, start_m, kmh, seconds, every=10, direction=1):
    """Fixes from a bus moving along the road at a steady speed."""
    out = []
    for i in range(0, seconds + 1, every):
        m = start_m + direction * kmh / 3.6 * i
        out.append((driver_id, LAT, LNG0 + m * DEG_PER_M, T0 + timedelta(seconds=i)))
    return out


def levels_at(segments, metres):
    found = []
    for seg in segments:
        lngs = [c[0] for c in seg['coordinates']]
        if min(lngs) <= LNG0 + metres * DEG_PER_M <= max(lngs):
            found.append(seg['level'])
    return found


class ComputeTrafficTests(TestCase):
    def test_labels_heavy_slow_and_moving_road_when_companies_agree(self):
        pings = []
        for bus in (1, 2, 3):
            pings += (
                drive(bus, 200, 40, 40)            # 200-650 m at 40 km/h
                + drive(10 + bus, 900, 14, 60)     # 900-1130 m at 14 km/h
                + drive(20 + bus, 1500, 3, 120)    # 1500-1600 m crawling
            )
        segments = compute_traffic(COORDS, [], sorted(pings, key=lambda r: (r[0], r[3])))
        self.assertEqual(levels_at(segments, 300), ['moving'])
        self.assertEqual(levels_at(segments, 1000), ['slow'])
        self.assertEqual(levels_at(segments, 1550), ['heavy'])
        self.assertEqual(levels_at(segments, 2100), [])
        self.assertNotIn('speed_kmh', segments[0])

    def test_one_other_bus_is_never_traceable(self):
        self.assertEqual(compute_traffic(COORDS, [], drive(7, 1500, 3, 120)), [])

    def test_the_passengers_own_bus_alone_is_shown(self):
        segments = compute_traffic(COORDS, [], drive(7, 1500, 3, 120), own_driver_id=7)
        self.assertEqual(levels_at(segments, 1550), ['heavy'])

    def test_a_bus_parked_off_a_stage_is_not_traffic(self):
        parked = drive(7, 1000, 0, 600)  # ten minutes without moving
        self.assertEqual(compute_traffic(COORDS, [], parked, own_driver_id=7), [])

    def test_a_short_stop_in_a_jam_is_traffic(self):
        stop = drive(7, 1000, 0, 120)
        segments = compute_traffic(COORDS, [], stop, own_driver_id=7)
        self.assertEqual(levels_at(segments, 1000), ['heavy'])

    def test_a_bus_waiting_at_a_stage_is_not_traffic(self):
        stage = (LAT, LNG0 + 1000 * DEG_PER_M)
        segments = compute_traffic(COORDS, [stage], drive(1, 1000, 0, 120), own_driver_id=1)
        self.assertEqual(segments, [])

    def test_buses_going_the_other_way_are_ignored(self):
        segments = compute_traffic(COORDS, [], drive(1, 1500, 30, 60, direction=-1), own_driver_id=1)
        self.assertEqual(segments, [])

    def test_fixes_off_the_road_are_ignored(self):
        far = [(1, LAT + 0.01, lng, t) for _, _, lng, t in drive(1, 300, 3, 60)]
        self.assertEqual(compute_traffic(COORDS, [], far, own_driver_id=1), [])

    def test_bad_geometry_is_rejected(self):
        self.assertIsNone(_route_coords({'coordinates': [[float('nan'), 0], [1, 1]]}))
        self.assertIsNone(_route_coords({'coordinates': [[200, 0], [1, 1]]}))

    def test_long_straight_segments_stay_cheap(self):
        started = time.monotonic()
        _Line([[0.0, 0.0], [2.0, 2.0]])  # one 300 km diagonal segment
        self.assertLess(time.monotonic() - started, 1)


class TrafficEndpointTests(APITestCase):
    def setUp(self):
        cache.clear()
        company = Company.objects.create(name='A', description='d', areas_served='N')
        self.route = Route.objects.create(
            company=company, name='R', start_point='CBD', end_point='W',
            price=Decimal('100.00'), geometry={'type': 'LineString', 'coordinates': COORDS},
        )
        stage = PickupStage.objects.create(
            route=self.route, name='S1', latitude=Decimal(str(LAT)),
            longitude=Decimal(str(round(LNG0 + 2100 * DEG_PER_M, 6))), order=1,
        )
        self.driver = Driver.objects.create(
            name='D', phone_number='0700000001', bus_number='K1', company=company,
            latitude=LAT, longitude=LNG0, location_updated_at=timezone.now(),
        )
        trip = Trip.objects.create(
            route=self.route, driver=self.driver, capacity=10, status='departed',
            departure_at=timezone.now(),
        )
        user = get_user_model().objects.create_user(
            username='p', password='x', phone_number='0711000001',
        )
        self.booking = Booking.objects.create(
            user=user, route=self.route, trip=trip, driver=self.driver,
            pickup_stage=stage, pickup_location='S1', seats=1,
            total_amount=Decimal('100.00'), status='confirmed',
        )
        self.client.force_authenticate(user=user)

    def test_only_real_fixes_are_kept(self):
        record_driver_fix(self.driver, LAT, LNG0)
        record_driver_fix(self.driver, LAT, LNG0, simulated=True)
        self.assertEqual(LocationPing.objects.count(), 1)

    def test_a_failed_ping_write_does_not_fail_the_gps_update(self):
        with mock.patch('drivers.traffic.LocationPing.objects.create', side_effect=RuntimeError('db')):
            record_driver_fix(self.driver, LAT, LNG0 + 0.001)
        self.driver.refresh_from_db()
        self.assertAlmostEqual(self.driver.longitude, LNG0 + 0.001)

    def test_live_location_includes_traffic_from_recent_fixes(self):
        LocationPing.objects.bulk_create(
            LocationPing(driver=self.driver, latitude=lat, longitude=lng, recorded_at=t)
            for _, lat, lng, t in drive(self.driver.id, 500, 3, 120)
        )
        resp = self.client.get(f'/api/bookings/{self.booking.id}/live-location/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual([s['level'] for s in resp.json()['traffic']], ['heavy'])
