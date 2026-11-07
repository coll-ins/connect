from django.core.cache import cache
from django.test import TestCase, override_settings

from companies.tests.test_trip_simulation import TripSimulationApiTests as Base
from users.throttles import LOGIN_FAILURES_PER_CLIENT, login_blocked, record_login_failure

DBCACHE = {'default': {'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
                       'LOCATION': 'django_cache_b'}}


class SimBreaks(Base):
    def test_advance_refused_when_trip_cancelled(self):
        sim_id = self.start().json()['simulation']['id']
        self.trip.status = 'cancelled'
        self.trip.save()
        r = self.client.post(f'/api/system/trip-simulations/{sim_id}/advance/')
        self.assertNotEqual(r.status_code, 200)

    def test_advance_refused_when_real_driver_gps_fresh(self):
        from django.utils import timezone
        sim_id = self.start().json()['simulation']['id']
        from drivers.models import Driver
        Driver.objects.filter(pk=self.driver.pk).update(location_updated_at=timezone.now())
        r = self.client.post(f'/api/system/trip-simulations/{sim_id}/advance/')
        self.assertNotEqual(r.status_code, 200)


@override_settings(CACHES=DBCACHE)
class CacheEvict(TestCase):
    def setUp(self):
        from django.core.management import call_command
        call_command('createcachetable', 'django_cache_b', verbosity=0)
        cache.clear()

    def test_flooding_other_phones_does_not_reset_victim_lockout(self):
        for _ in range(LOGIN_FAILURES_PER_CLIENT):
            record_login_failure('0712345678', '1.1.1.1')
        self.assertTrue(login_blocked('0712345678', '1.1.1.1'))
        for i in range(400):
            record_login_failure(f'07{i:08d}', '2.2.2.2')
        self.assertTrue(login_blocked('0712345678', '1.1.1.1'))
