from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


class SignupPhoneThrottle(SimpleRateThrottle):
    """Limit account creation attempts per phone number."""
    scope = 'signup'

    def get_cache_key(self, request, view):
        try:
            raw = request.data.get('phone_number')
        except Exception:
            return None
        digits = ''.join(ch for ch in str(raw or '') if ch.isdigit())
        if not digits:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': digits[-9:]}


class LoginIPThrottle(AnonRateThrottle):
    # Per-IP limit for login only, separate from the general anon bucket.
    scope = 'login_ip'


# Login lockout counts FAILED attempts only, so knowing someone's phone number
# is not enough to lock them out:
#   - per phone + client IP: 10 failures/hour stops guessing from one client;
#   - per phone across all IPs: 100 failures/hour slows distributed guessing
#     while an attacker would need many IPs to block the real owner.
LOGIN_FAILURE_WINDOW = 60 * 60
LOGIN_FAILURES_PER_CLIENT = 10
LOGIN_FAILURES_PER_PHONE = 100


def _phone_ident(raw):
    digits = ''.join(ch for ch in str(raw or '') if ch.isdigit())
    return digits[-9:] or None


def _failure_keys(phone, ip):
    from django.core.cache import cache

    ident = _phone_ident(phone)
    if not ident:
        return None, None
    generation = cache.get(f'login_gen:{ident}', 0)
    return f'login_fail:{ident}', f'login_fail:{ident}:{generation}:{ip}'


def login_blocked(phone, ip):
    from django.core.cache import cache

    phone_key, client_key = _failure_keys(phone, ip)
    if not phone_key:
        return False
    return (
        cache.get(client_key, 0) >= LOGIN_FAILURES_PER_CLIENT
        or cache.get(phone_key, 0) >= LOGIN_FAILURES_PER_PHONE
    )


def record_login_failure(phone, ip):
    from django.core.cache import cache

    for key in _failure_keys(phone, ip):
        if not key:
            continue
        if cache.add(key, 1, LOGIN_FAILURE_WINDOW):
            continue
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, LOGIN_FAILURE_WINDOW)


def clear_login_failures(phone, ip=None):
    """Reset lockout for a phone (all clients). Used on success and by ensure_superuser."""
    from django.core.cache import cache

    ident = _phone_ident(phone)
    if not ident:
        return
    cache.delete(f'login_fail:{ident}')
    generation_key = f'login_gen:{ident}'
    if not cache.add(generation_key, 1, None):
        try:
            cache.incr(generation_key)
        except ValueError:
            cache.set(generation_key, 1, None)
