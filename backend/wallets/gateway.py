"""Transfer gateway for wallet withdrawals: one small contract, two adapters.

Contract (a subclass of Gateway):
    ensure_recipient(phone) -> recipient_code          raises GatewayRefused
    send(payout, recipient_code) -> SendResult         never raises on gateway trouble
    status(reference) -> one of STATUS_VALUES          never raises on gateway trouble

send() answers ACCEPTED, REFUSED (a definite "no money moved": the caller
reverses) or UNCERTAIN (timeout, 5xx, unreadable body: the money may have
moved, so the caller must NEVER reverse; the sweep asks status()).

UNVERIFIED: every Paystack name and value in PaystackTransfers below was
written from memory of the public Transfers API, not checked against the live
docs or an account. They are the named constants right under this docstring so
one place can be corrected after the live test.
"""
import logging
from collections import namedtuple

import requests
from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

ACCEPTED = 'accepted'
REFUSED = 'refused'
UNCERTAIN = 'uncertain'
SendResult = namedtuple('SendResult', 'outcome detail')

STATUS_VALUES = ('pending', 'success', 'failed', 'reversed', 'otp', 'review', 'not_found', 'error')

# --- Paystack names and values (all UNVERIFIED, see module docstring) ---------
API = 'https://api.paystack.co'
TIMEOUT_SECONDS = 10
RECIPIENT_PATH = '/transferrecipient'
TRANSFER_PATH = '/transfer'
VERIFY_PATH = '/transfer/verify/'
RECIPIENT_TYPE = 'mobile_money'
BANK_CODE = 'MPESA'
CURRENCY = 'KES'
SOURCE = 'balance'
RECIPIENT_NAME = 'Connect wallet'
TRANSFER_REASON = 'Connect wallet withdrawal'
ACCOUNT_NUMBER_FORMAT = 'local'  # '0712345678'; the alternative is '254712345678'
SEND_ACCEPTED_STATUSES = {'pending', 'success', 'otp', 'received', 'processing', 'queued'}
VERIFY_STATUS_MAP = {
    'success': 'success', 'failed': 'failed', 'reversed': 'reversed', 'otp': 'otp',
    'pending': 'pending', 'processing': 'pending', 'received': 'pending', 'queued': 'pending',
    'rejected': 'review', 'blocked': 'review',
}
# 4xx answers that do not prove "nothing was sent": a rate limit or a timeout code.
UNCERTAIN_HTTP_CODES = {408, 425, 429}


class GatewayRefused(Exception):
    """The gateway definitely did not do what was asked."""


class Gateway:
    def ensure_recipient(self, phone):
        raise NotImplementedError

    def send(self, payout, recipient_code):
        raise NotImplementedError

    def status(self, reference):
        raise NotImplementedError


def _assert_not_atomic():
    # A network call inside a transaction holds row locks for as long as the
    # gateway takes, and a rollback would undo a transfer that really happened.
    if connection.in_atomic_block:
        raise RuntimeError('transfer gateway called inside a database transaction')


def _headers():
    return {
        'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json',
    }


def _body(response):
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _account_number(phone):
    # phone is canonical '+2547XXXXXXXX' (the caller guarantees it)
    digits = phone.lstrip('+')
    return '0' + digits[3:] if ACCOUNT_NUMBER_FORMAT == 'local' else digits


class PaystackTransfers(Gateway):
    """Real adapter. Never exercised against live Paystack: UNVERIFIED."""

    def ensure_recipient(self, phone):
        _assert_not_atomic()
        payload = {
            'type': RECIPIENT_TYPE, 'name': RECIPIENT_NAME,
            'account_number': _account_number(phone),
            'bank_code': BANK_CODE, 'currency': CURRENCY,
        }
        try:
            response = requests.post(
                API + RECIPIENT_PATH, json=payload, headers=_headers(), timeout=TIMEOUT_SECONDS)
        except requests.RequestException:
            raise GatewayRefused('Could not reach the payment gateway.')
        body = _body(response)
        code = ((body or {}).get('data') or {}).get('recipient_code') if response.status_code in (200, 201) else None
        if not code or not isinstance(code, str):
            raise GatewayRefused((body or {}).get('message') or 'Recipient could not be created.')
        return code

    def send(self, payout, recipient_code):
        _assert_not_atomic()
        payload = {
            'source': SOURCE,
            'amount': int(payout.amount * 100),
            'recipient': recipient_code,
            'reference': payout.reference,
            'currency': CURRENCY,
            'reason': TRANSFER_REASON,
        }
        try:
            response = requests.post(
                API + TRANSFER_PATH, json=payload, headers=_headers(), timeout=TIMEOUT_SECONDS)
        except requests.RequestException:
            return SendResult(UNCERTAIN, 'network error or timeout')
        code = response.status_code
        body = _body(response)
        message = str((body or {}).get('message') or '')[:200]
        if code >= 500 or code in UNCERTAIN_HTTP_CODES:
            return SendResult(UNCERTAIN, f'HTTP {code}')
        if 400 <= code < 500:
            lowered = message.lower()
            if 'reference' in lowered and ('exist' in lowered or 'duplicate' in lowered):
                return SendResult(UNCERTAIN, message)  # the first send may have gone through
            return SendResult(REFUSED, message or f'HTTP {code}')
        data = (body or {}).get('data')
        if (code == 200 and body and body.get('status') is True and isinstance(data, dict)
                and data.get('status') in SEND_ACCEPTED_STATUSES and data.get('transfer_code')):
            return SendResult(ACCEPTED, str(data['transfer_code']))
        return SendResult(UNCERTAIN, 'unreadable response')

    def status(self, reference):
        _assert_not_atomic()
        try:
            response = requests.get(
                API + VERIFY_PATH + reference, headers=_headers(), timeout=TIMEOUT_SECONDS)
        except requests.RequestException:
            return 'error'
        if response.status_code == 404:
            return 'not_found'
        body = _body(response)
        data = (body or {}).get('data')
        if response.status_code != 200 or not isinstance(data, dict):
            return 'error'
        raw = data.get('status')
        return VERIFY_STATUS_MAP.get(raw.lower(), 'error') if isinstance(raw, str) else 'error'


class FakeTransfers(Gateway):
    """Scriptable gateway for tests. Records every call and whether a transaction was open."""

    def __init__(self):
        self.calls = []
        self.send_results = []   # consumed in order; an Exception instance is raised
        self.statuses = {}       # reference -> status string or Exception
        self.recipient_error = None
        self.on_send = None

    def _record(self, name, args, **extra):
        self.calls.append({'name': name, 'args': args, 'atomic': connection.in_atomic_block, **extra})

    def ensure_recipient(self, phone):
        self._record('ensure_recipient', (phone,))
        if self.recipient_error:
            raise GatewayRefused(self.recipient_error)
        return f'RCP_fake_{phone[-4:]}'

    def send(self, payout, recipient_code):
        self._record('send', (recipient_code,), payout_amount=payout.amount, reference=payout.reference)
        if self.on_send:
            self.on_send(payout)
        result = self.send_results.pop(0) if self.send_results else SendResult(ACCEPTED, 'TRF_fake')
        if isinstance(result, Exception):
            raise result
        return result

    def status(self, reference):
        self._record('status', (reference,))
        result = self.statuses.get(reference, 'not_found')
        if isinstance(result, Exception):
            raise result
        return result


def get_gateway():
    return PaystackTransfers()
