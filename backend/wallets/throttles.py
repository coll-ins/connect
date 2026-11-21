from rest_framework.throttling import SimpleRateThrottle


class TopUpThrottle(SimpleRateThrottle):
    """Each top-up starts a Paystack transaction: limit it per user."""
    scope = 'wallet_topup'
    # Class-level so settings.py needs no DEFAULT_THROTTLE_RATES entry.
    rate = '10/hour'

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': request.user.pk}


class WithdrawThrottle(SimpleRateThrottle):
    """Every request can move money out: limit them per user."""
    scope = 'wallet_withdraw'
    rate = '5/hour'

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': request.user.pk}
