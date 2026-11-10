"""Web Push (RFC 8291 payload encryption, RFC 8292 VAPID) for phones with the app closed.

No outside account is needed: the VAPID key pair is derived from SECRET_KEY,
so push works on every deploy without extra settings. Sending never raises and
runs off the request thread, so a slow push service cannot slow a GPS post.
"""
import base64
import json
import logging
import os
import re
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.db import close_old_connections

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='webpush')
# Order of the P-256 group: a derived private scalar must be in [1, n-1].
_P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def unb64u(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _hkdf(salt, ikm, info, length):
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


@lru_cache(maxsize=1)
def _vapid_key():
    seed = _hkdf(b'connect-vapid', settings.SECRET_KEY.encode(), b'vapid-p256', 48)
    return ec.derive_private_key(int.from_bytes(seed, 'big') % (_P256_N - 1) + 1, ec.SECP256R1())


def _raw_public(key):
    return key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def public_key():
    """applicationServerKey the browser subscribes with (base64url, 65 bytes)."""
    return b64u(_raw_public(_vapid_key()))


def _vapid_header(endpoint):
    parts = urlsplit(endpoint)
    claims = {
        'aud': f'{parts.scheme}://{parts.netloc}',
        'exp': int(time.time()) + 12 * 3600,
        'sub': 'mailto:' + (settings.DEFAULT_FROM_EMAIL or 'noreply@connect.invalid'),
    }
    signing_input = (
        b64u(json.dumps({'typ': 'JWT', 'alg': 'ES256'}).encode())
        + '.' + b64u(json.dumps(claims, separators=(',', ':')).encode())
    )
    der = _vapid_key().sign(signing_input.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    token = signing_input + '.' + b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))
    return f'vapid t={token}, k={public_key()}'


def encrypt(payload, p256dh, auth, _sender_key=None, _salt=None):
    """aes128gcm body for one subscription (RFC 8291). The _ args are for test vectors."""
    ua_public = unb64u(p256dh)
    auth_secret = unb64u(auth)
    sender = _sender_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(sender)
    shared = sender.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    ikm = _hkdf(auth_secret, shared, b'WebPush: info\x00' + ua_public + as_public, 32)
    salt = _salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = _hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
    body = AESGCM(cek).encrypt(nonce, payload + b'\x02', None)
    return salt + struct.pack('!IB', 4096, len(as_public)) + as_public + body


# The server POSTs to the endpoint, so only real browser push services, written
# plainly: no userinfo, backslashes, spaces or odd ports that parsers read differently.
PUSH_HOSTS = ('fcm.googleapis.com', 'updates.push.services.mozilla.com',
              '.push.apple.com', '.notify.windows.com')
_ENDPOINT = re.compile(r'https://([a-z0-9.-]+)(?::443)?/[A-Za-z0-9._~%/:=+?&-]*', re.ASCII)


def endpoint_allowed(endpoint):
    if not isinstance(endpoint, str) or len(endpoint) > 1000:
        return False
    match = _ENDPOINT.fullmatch(endpoint)
    if not match:
        return False
    host = match.group(1)
    return any(host == h or (h.startswith('.') and host.endswith(h)) for h in PUSH_HOSTS)


def _deliver(sub_id, endpoint, p256dh, auth, data):
    from users.models import PushSubscription

    try:
        if not endpoint_allowed(endpoint):
            PushSubscription.objects.filter(pk=sub_id).delete()
            return
        resp = requests.post(
            endpoint,
            data=encrypt(data, p256dh, auth),
            headers={
                'Authorization': _vapid_header(endpoint),
                'Content-Encoding': 'aes128gcm',
                'Content-Type': 'application/octet-stream',
                'TTL': '3600',
                'Urgency': 'high',
            },
            timeout=8,
            allow_redirects=False,
        )
        if resp.status_code in (404, 410):
            # The phone unsubscribed or reinstalled: forget it.
            PushSubscription.objects.filter(pk=sub_id).delete()
        elif resp.status_code >= 400:
            logger.warning('push %s rejected: %s %s', sub_id, resp.status_code, resp.text[:200])
    except Exception:
        logger.exception('push %s failed', sub_id)
    finally:
        close_old_connections()


def notify_users(user_ids, title, body, url='/', tag=None):
    """Queue a notification to every phone of these users. Never raises."""
    try:
        from users.models import PushSubscription

        data = json.dumps({'title': title, 'body': body, 'url': url, 'tag': tag}).encode()
        subs = PushSubscription.objects.filter(user_id__in=set(user_ids)).values_list(
            'id', 'endpoint', 'p256dh', 'auth')
        for sub in subs:
            _pool.submit(_deliver, *sub, data)
    except Exception:
        logger.exception('push queue failed')
