from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import UnappliedPayment
from companies.models import Trip
from deliveries.models import Parcel
from deliveries.services import deliver, pick_up, settle_stale_parcels
from deliveries.tests.test_parcels import ParcelTests as _Base


@patch('notifications.sms.send_admin_alert_sms')
class StaleParcelTests(APITestCase):
    """A paid parcel on a trip that is over must never keep the sender's money."""

    # Reuse the parcel fixture without re-running its tests.
    setUp, body, create, paid = _Base.setUp, _Base.body, _Base.create, _Base.paid

    def _trip(self, status, hours_ago=1):
        Trip.objects.filter(pk=self.trip.pk).update(
            status=status, departure_at=timezone.now() - timedelta(hours=hours_ago))

    def test_cancelled_trip_refunds_paid_parcel(self, sms):
        p = self.paid()
        self._trip('cancelled')
        self.assertEqual(settle_stale_parcels(), (1, 0))
        p.refresh_from_db()
        self.assertEqual(p.status, 'cancelled')
        row = UnappliedPayment.objects.get(reference=p.provider_reference)
        self.assertEqual((row.kind, row.status, row.amount), ('parcel', 'refund_due', p.price))
        self.assertEqual(settle_stale_parcels(), (0, 0))  # idempotent

    def test_completed_trip_expires_never_picked_up_parcel(self, sms):
        p = self.paid()
        self._trip('completed')
        settle_stale_parcels()
        p.refresh_from_db()
        self.assertEqual(p.status, 'expired')
        self.assertTrue(UnappliedPayment.objects.filter(
            reference=p.provider_reference, status='refund_due').exists())

    def test_running_trip_is_left_alone(self, sms):
        p = self.paid()
        self._trip('departed', hours_ago=2)
        self.assertEqual(settle_stale_parcels(), (0, 0))
        p.refresh_from_db()
        self.assertEqual(p.status, 'paid')

    def test_undelivered_parcel_is_flagged_but_can_still_be_delivered(self, sms):
        p = self.paid()
        self._trip('departed')
        pick_up(parcel_id=p.id, driver=self.driver)
        Parcel.objects.filter(pk=p.pk).update(picked_up_at=timezone.now() - timedelta(hours=49))
        self._trip('completed', hours_ago=50)
        self.assertEqual(settle_stale_parcels(), (0, 1))
        p.refresh_from_db()
        self.assertEqual(p.status, 'failed_delivery')
        sms.assert_called_once()
        self.assertFalse(UnappliedPayment.objects.filter(reference=p.provider_reference).exists())
        deliver(parcel_id=p.id, driver=self.driver, pin=p.handover_pin)
        p.refresh_from_db()
        self.assertEqual(p.status, 'delivered')

    def test_unpaid_parcel_on_a_gone_trip_expires(self, sms):
        p = Parcel.objects.get(id=self.create().data['id'])
        self._trip('cancelled')
        settle_stale_parcels()
        p.refresh_from_db()
        self.assertEqual(p.status, 'expired')
