import hashlib
import hmac
import json
from unittest.mock import patch

from django.conf import settings
from django.http import HttpResponse
from rest_framework.test import APITestCase

URL = "/api/bookings/webhooks/paystack/"


def _post(client, payload, sign=True):
    body = json.dumps(payload).encode()
    sig = (hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body, hashlib.sha512).hexdigest()
           if sign else "bad")
    return client.post(URL, data=body, content_type="application/json",
                       HTTP_X_PAYSTACK_SIGNATURE=sig)


class WebhookRoutingTests(APITestCase):
    def test_signed_refund_events_reach_the_refund_handler(self):
        for ev in ("refund.processed", "refund.failed", "refund.pending"):
            with patch("bookings.views.paystack_refund_webhook",
                       return_value=HttpResponse(status=200)) as m:
                resp = _post(self.client, {"event": ev, "data": {"id": 1}})
            self.assertEqual(resp.status_code, 200, ev)
            self.assertEqual(m.call_count, 1, f"{ev} never reached the refund handler")

    def test_forged_refund_event_is_refused_before_routing(self):
        with patch("bookings.views.paystack_refund_webhook",
                   return_value=HttpResponse(status=200)) as m:
            resp = _post(self.client, {"event": "refund.processed", "data": {}}, sign=False)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(m.call_count, 0)

    def test_other_events_do_not_reach_the_refund_handler(self):
        with patch("bookings.views.paystack_refund_webhook",
                   return_value=HttpResponse(status=200)) as m:
            resp = _post(self.client, {"event": "transfer.success", "data": {}})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(m.call_count, 0)
