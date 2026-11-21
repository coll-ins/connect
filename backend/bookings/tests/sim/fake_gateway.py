"""Test-only fake Paystack and SMS, with fault injection and signed webhooks.

One interception point: every `requests.get/post` ends in
`requests.sessions.Session.request`, so patching that catches all call sites
(bookings views and services, connect.paystack_extra, wallets.gateway,
reconcile_refunds, the geocoder). A request to any other host or path is
recorded in `leaks` and the invariants fail on it; it is never allowed out.

What this proves: the code is consistent with ITS OWN assumptions about
Paystack (docs/plan.md V9). The fake encodes those assumptions, so a green run
is not evidence that real Paystack behaves this way.
"""
import hashlib
import hmac
import itertools
import json
import threading
from collections import defaultdict, deque
from decimal import Decimal
from unittest import mock
from urllib.parse import unquote, urlparse

import requests
from django.conf import settings
from django.db import connection

HOST = 'api.paystack.co'
BOOKING_WEBHOOK = '/api/bookings/webhooks/paystack/'

# Fault kinds. 'timeout_after_accept' applies the effect at the gateway and
# then times out: the dangerous ambiguous case (money moved, caller unsure).
TIMEOUT = 'timeout'
TIMEOUT_AFTER_ACCEPT = 'timeout_after_accept'
HTTP_500 = 'http_500'
HTTP_429 = 'http_429'
HTTP_400 = 'http_400'
UNREADABLE = 'unreadable'
FAULT_KINDS = (TIMEOUT, TIMEOUT_AFTER_ACCEPT, HTTP_500, HTTP_429, HTTP_400, UNREADABLE)


def sign(body):
    return hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode('utf-8'), body, hashlib.sha512).hexdigest()


def subunits(kes):
    return int((Decimal(str(kes)) * 100).to_integral_value())


# ------------------------------------------------------------------ events

def charge_success(reference, amount_kes, currency='KES', metadata=None, status='success'):
    return {'event': 'charge.success', 'data': {
        'id': abs(hash(reference)) % 10**9, 'reference': reference, 'status': status,
        'amount': subunits(amount_kes), 'currency': currency,
        'metadata': metadata or {}}}


def refund_event(name, transaction_reference, refund_id, amount_kes):
    # Which field carries the refund id in the real event is UNVERIFIED
    # (docs/evidence.md BE-1b); the code accepts either, the fake sends `id`.
    return {'event': f'refund.{name}', 'data': {
        'id': refund_id, 'transaction_reference': transaction_reference,
        'amount': subunits(amount_kes), 'currency': 'KES', 'status': name}}


def transfer_event(name, reference, amount_kes, currency='KES'):
    return {'event': f'transfer.{name}', 'data': {
        'reference': reference, 'transfer_code': 'TRF_sim', 'status': name,
        'amount': subunits(amount_kes), 'currency': currency}}


def post_event(client, event, *, signature='valid', path=BOOKING_WEBHOOK, body=None):
    """POST a webhook with a signature computed over the exact bytes sent."""
    body = body if body is not None else json.dumps(event).encode('utf-8')
    extra = {}
    if signature == 'valid':
        extra['HTTP_X_PAYSTACK_SIGNATURE'] = sign(body)
    elif signature is not None:
        extra['HTTP_X_PAYSTACK_SIGNATURE'] = signature
    return client.generic('POST', path, body, content_type='application/json', **extra)


# ------------------------------------------------------------------ the fake

class FakePaystack:
    def __init__(self):
        self.lock = threading.RLock()
        self.calls = []           # every request: method, path, json, params, atomic
        self.leaks = []           # requests to a host/path the fake does not implement
        self.sms = []             # (message, phones, label, atomic)
        self.charges = {}         # reference -> dict
        self.refunds = []         # accepted refunds
        self.transfers = {}       # reference -> dict
        self.recipients = {}
        self._faults = defaultdict(deque)
        self._sticky = {}
        self._hooks = {}
        self._ids = itertools.count(1000)

    # ---- wiring
    def install(self, testcase):
        patcher = mock.patch.object(
            requests.sessions.Session, 'request', autospec=True, side_effect=self._request)
        patcher.start()
        testcase.addCleanup(patcher.stop)
        sms = mock.patch('notifications.sms._send', side_effect=self._sms)
        sms.start()
        testcase.addCleanup(sms.stop)
        return self

    def _sms(self, message, phones, label):
        with self.lock:
            self.sms.append((message, tuple(phones), label, connection.in_atomic_block))
        return True

    # ---- fault injection
    def fault(self, endpoint, kind, times=1, message='refused by the fake'):
        """Fail the next `times` calls to `endpoint` (times=None: until cleared)."""
        assert kind in FAULT_KINDS, kind
        spec = (kind, message)
        with self.lock:
            if times is None:
                self._sticky[endpoint] = spec
            else:
                self._faults[endpoint].extend([spec] * times)

    def clear_faults(self):
        with self.lock:
            self._faults.clear()
            self._sticky.clear()

    def hook(self, endpoint, fn):
        """Run fn(request_record) at the start of every call to `endpoint`."""
        self._hooks[endpoint] = fn

    def _next_fault(self, endpoint):
        with self.lock:
            if self._faults[endpoint]:
                return self._faults[endpoint].popleft()
            return self._sticky.get(endpoint)

    # ---- customer behaviour
    def customer_pays(self, reference, amount_kes=None, currency='KES', metadata=None):
        """The customer completes (or over/under pays) a checkout. Returns the charge.success event."""
        with self.lock:
            charge = self.charges.setdefault(reference, {
                'amount': subunits(amount_kes if amount_kes is not None else 0),
                'currency': currency, 'metadata': metadata or {}, 'paid': None})
            paid = subunits(amount_kes) if amount_kes is not None else charge['amount']
            charge.update(paid=paid, currency=currency)
            if metadata:
                charge['metadata'] = metadata
        return charge_success(reference, Decimal(paid) / 100, currency, charge['metadata'])

    def set_transfer_status(self, reference, status):
        with self.lock:
            self.transfers[reference]['status'] = status

    # ---- gateway truth, used by invariants
    def accepted_refunds(self, reference=None):
        with self.lock:
            return [r for r in self.refunds
                    if reference is None or r['transaction'] == reference]

    def refunded_subunits(self, reference):
        return sum(r['amount'] for r in self.accepted_refunds(reference))

    def calls_to(self, name):
        with self.lock:
            return [c for c in self.calls if c['endpoint'] == name]

    def calls_inside_atomic(self):
        with self.lock:
            return [c for c in self.calls if c['atomic']] + [
                {'endpoint': 'sms', 'path': s[0][:40], 'atomic': True}
                for s in self.sms if s[3]]

    # ---- the request router
    @staticmethod
    def _response(url, status, body):
        r = requests.Response()
        r.status_code = status
        r.url = url
        r._content = body if isinstance(body, bytes) else json.dumps(body).encode('utf-8')
        r.headers['Content-Type'] = 'application/json'
        r.encoding = 'utf-8'
        return r

    @staticmethod
    def _classify(method, path):
        if method == 'POST' and path == '/transaction/initialize':
            return 'initialize'
        if method == 'POST' and path == '/charge':
            return 'charge'
        if method == 'GET' and path.startswith('/transaction/verify/'):
            return 'verify'
        if method == 'POST' and path == '/refund':
            return 'refund'
        if method == 'GET' and path == '/refund':
            return 'refund_list'
        if method == 'POST' and path == '/transferrecipient':
            return 'recipient'
        if method == 'POST' and path == '/transfer':
            return 'transfer'
        if method == 'GET' and path.startswith('/transfer/verify/'):
            return 'transfer_verify'
        return None

    def _request(self, session, method, url, **kw):
        parsed = urlparse(url)
        method = method.upper()
        endpoint = self._classify(method, parsed.path) if parsed.netloc == HOST else None
        record = {
            'method': method, 'url': url, 'path': parsed.path, 'endpoint': endpoint or 'leak',
            'json': kw.get('json'), 'params': kw.get('params') or {},
            'atomic': connection.in_atomic_block,
        }
        with self.lock:
            self.calls.append(record)
        if endpoint is None:
            with self.lock:
                self.leaks.append(record)
            raise requests.ConnectionError(f'sim: unexpected outbound call {method} {url}')
        hook = self._hooks.get(endpoint)
        if hook:
            hook(record)
        fault = self._next_fault(endpoint)
        if fault and fault[0] == TIMEOUT:
            raise requests.exceptions.Timeout('sim: timeout')
        if fault and fault[0] == HTTP_500:
            return self._response(url, 500, {'status': False, 'message': 'sim: internal error'})
        if fault and fault[0] == HTTP_429:
            return self._response(url, 429, {'status': False, 'message': 'sim: slow down'})
        if fault and fault[0] == HTTP_400:
            return self._response(url, 400, {'status': False, 'message': fault[1]})
        if fault and fault[0] == UNREADABLE:
            return self._response(url, 200, b'<html>sim: not json</html>')
        response = getattr(self, f'_do_{endpoint}')(record, url, kw)
        if fault and fault[0] == TIMEOUT_AFTER_ACCEPT:
            raise requests.exceptions.Timeout('sim: timeout after the gateway accepted')
        return response

    # ---- endpoints
    def _do_initialize(self, rec, url, kw):
        body = kw.get('json') or {}
        with self.lock:
            self.charges.setdefault(body['reference'], {
                'amount': body['amount'], 'currency': body.get('currency', 'KES'),
                'metadata': body.get('metadata') or {}, 'paid': None})
        return self._response(url, 200, {'status': True, 'message': 'Authorization URL created', 'data': {
            'authorization_url': f"https://checkout.invalid/{body['reference']}",
            'access_code': 'sim', 'reference': body['reference']}})

    def _do_charge(self, rec, url, kw):
        body = kw.get('json') or {}
        with self.lock:
            self.charges.setdefault(body['reference'], {
                'amount': body['amount'], 'currency': body.get('currency', 'KES'),
                'metadata': body.get('metadata') or {}, 'paid': None})
        return self._response(url, 200, {'status': True, 'message': 'Charge attempted', 'data': {
            'reference': body['reference'], 'status': 'pay_offline',
            'display_text': 'Check your phone'}})

    def _do_verify(self, rec, url, kw):
        ref = unquote(rec['path'].rsplit('/', 1)[1])
        with self.lock:
            charge = self.charges.get(ref)
        if charge is None:
            return self._response(url, 404, {'status': False, 'message': 'Transaction reference not found'})
        paid = charge['paid']
        return self._response(url, 200, {'status': True, 'message': 'Verification successful', 'data': {
            'reference': ref, 'status': 'success' if paid is not None else 'abandoned',
            'amount': paid if paid is not None else charge['amount'],
            'currency': charge['currency'], 'metadata': charge['metadata']}})

    def _do_refund(self, rec, url, kw):
        body = kw.get('json') or {}
        ref, amount = body.get('transaction'), body.get('amount')
        with self.lock:
            charge = self.charges.get(ref)
            if charge is None or charge['paid'] is None:
                return self._response(url, 400, {'status': False, 'message': 'Transaction reference not found'})
            if not isinstance(amount, int) or amount < 500:
                return self._response(url, 400, {'status': False, 'message': 'Amount is below the refund minimum'})
            if self.refunded_subunits(ref) + amount > charge['paid']:
                return self._response(url, 400, {'status': False, 'message': 'Amount is greater than the amount available for refund'})
            note = str(body.get('merchant_note') or '')
            kind = ('booking' if note.startswith('CONNECT booking refund')
                    else 'unapplied' if note.startswith('CONNECT unapplied payment') else 'other')
            refund = {'id': next(self._ids), 'transaction': ref, 'amount': amount,
                      'status': 'pending', 'kind': kind}
            self.refunds.append(refund)
        return self._response(url, 200, {'status': True, 'message': 'Refund has been queued for processing', 'data': {
            'id': refund['id'], 'status': 'pending', 'amount': amount,
            'transaction': {'reference': ref}}})

    def _do_refund_list(self, rec, url, kw):
        ref = rec['params'].get('reference')
        data = [{'id': r['id'], 'amount': r['amount'], 'status': r['status'],
                 'transaction_reference': ref, 'currency': 'KES'}
                for r in self.accepted_refunds(ref)]
        return self._response(url, 200, {'status': True, 'data': data})

    def _do_recipient(self, rec, url, kw):
        body = kw.get('json') or {}
        with self.lock:
            code = self.recipients.setdefault(body.get('account_number'), f'RCP_sim{len(self.recipients) + 1}')
        return self._response(url, 200, {'status': True, 'data': {'recipient_code': code}})

    def _do_transfer(self, rec, url, kw):
        body = kw.get('json') or {}
        ref = body.get('reference')
        with self.lock:
            if ref in self.transfers:
                return self._response(url, 400, {'status': False, 'message': 'Transfer reference already exists (duplicate)'})
            self.transfers[ref] = {'amount': body.get('amount'), 'status': 'pending',
                                   'code': f'TRF_sim{len(self.transfers) + 1}'}
            code = self.transfers[ref]['code']
        return self._response(url, 200, {'status': True, 'message': 'Transfer has been queued', 'data': {
            'transfer_code': code, 'status': 'pending', 'reference': ref,
            'amount': body.get('amount'), 'currency': 'KES'}})

    def _do_transfer_verify(self, rec, url, kw):
        ref = unquote(rec['path'].rsplit('/', 1)[1])
        with self.lock:
            transfer = self.transfers.get(ref)
        if transfer is None:
            return self._response(url, 404, {'status': False, 'message': 'Transfer not found'})
        return self._response(url, 200, {'status': True, 'data': {
            'status': transfer['status'], 'reference': ref}})
