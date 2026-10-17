from rest_framework.throttling import SimpleRateThrottle


class LoginPhoneThrottle(SimpleRateThrottle):
    """Limit login attempts per phone number, however many IPs they come from."""
    scope = 'login'

    def get_cache_key(self, request, view):
        try:
            raw = request.data.get('phone_number')
        except Exception:
            return None
        digits = ''.join(ch for ch in str(raw or '') if ch.isdigit())
        if not digits:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': digits[-9:]}
