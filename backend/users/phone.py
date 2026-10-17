"""One canonical format for Kenyan mobile numbers: +2547XXXXXXXX / +2541XXXXXXXX."""
import re

KENYA_MOBILE = re.compile(r'^\+254[17]\d{8}$')


def canonical_phone(value):
    """
    Return the canonical form of a Kenyan mobile number. Anything that is not a
    recognisable Kenyan mobile is returned stripped but otherwise unchanged,
    so a foreign or malformed number is never turned into a different number.
    """
    if value is None:
        return None
    raw = str(value).strip()
    digits = ''.join(ch for ch in raw if ch.isdigit())
    if not digits:
        return raw
    if digits.startswith('2540'):          # "+254 0712..." typo
        digits = '254' + digits[4:]
    if digits.startswith('254'):
        candidate = '+' + digits
    elif digits.startswith('0'):
        candidate = '+254' + digits[1:]
    else:
        candidate = '+254' + digits
    return candidate if KENYA_MOBILE.match(candidate) else raw


def phone_variants(value):
    """Every stored spelling a number may have: raw, canonical, 07... and 2547..."""
    raw = str(value).strip() if value else ''
    if not raw:
        return set()
    canon = canonical_phone(raw)
    variants = {raw, canon}
    if KENYA_MOBILE.match(canon):
        variants.update({'0' + canon[4:], canon[1:]})
    return variants
