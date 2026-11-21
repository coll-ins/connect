"""Lockout in front of the Django admin login, using the same counters as /api/users/login/."""
import unicodedata

from django.contrib import admin
from django.http import HttpResponse

from .models import CustomUser
from .throttles import (
    LoginIPThrottle,
    login_blocked,
    record_login_failure,
)


def locked_admin_login(request, extra_context=None):
    if request.method != 'POST':
        return admin.site.login(request, extra_context)

    # The admin form strips the name and applies NFKC before it authenticates;
    # count the name the same way or a padded spelling is never counted.
    submitted = unicodedata.normalize('NFKC', str(request.POST.get('username', '')).strip())
    ip = LoginIPThrottle().get_ident(request)
    # The counters are keyed on a phone number; an admin signs in with a
    # username, so count against the phone of the account that name belongs to,
    # or against the client address when nobody owns the name.
    owner = CustomUser.objects.filter(username=submitted).only('phone_number').first()
    key = owner.phone_number if owner is not None else ''
    if not any(ch.isdigit() for ch in key):
        key = f'ip:{ip}'

    if login_blocked(key, ip):
        return HttpResponse('Too many failed attempts. Try again in an hour.', status=429)

    response = admin.site.login(request, extra_context)
    # A success must not clear the counter: it is shared with the API login,
    # and clearing it would also reset that lockout.
    if response.status_code != 302:
        record_login_failure(key, ip)
    return response
