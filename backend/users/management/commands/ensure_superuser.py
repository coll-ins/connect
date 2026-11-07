"""Create or repair the platform admin from ADMIN_PHONE / ADMIN_PASSWORD.

Runs on every deploy. Does nothing unless both variables are set, and prints
only "superuser ensured" so no credential reaches the logs.
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction

from users.phone import canonical_phone, phone_variants
from users.throttles import clear_login_failures


class Command(BaseCommand):
    help = 'Ensure a platform superuser exists (ADMIN_PHONE, ADMIN_PASSWORD).'

    def handle(self, *args, **opts):
        phone = canonical_phone(os.environ.get('ADMIN_PHONE', ''))
        password = os.environ.get('ADMIN_PASSWORD', '')
        if not phone or not password:
            return
        User = get_user_model()
        user = User.objects.filter(phone_number__in=phone_variants(phone)).first()
        if user is not None and user.company_id and not user.is_superuser:
            # Never turn a company staff account into a platform admin.
            self.stderr.write('superuser not ensured: ADMIN_PHONE belongs to a company account')
            return
        if user is None:
            username = os.environ.get('ADMIN_USERNAME') or f'admin{phone[-9:]}'
            user = User(username=username)
        user.phone_number = phone
        user.is_superuser = user.is_staff = user.is_active = True
        if hasattr(user, 'role'):
            user.role = 'platform_admin'
        user.set_password(password)
        try:
            with transaction.atomic():
                user.save()
        except IntegrityError:
            # A taken ADMIN_USERNAME must not stop the server from starting.
            self.stderr.write('superuser not ensured: ADMIN_USERNAME is already taken')
            return
        clear_login_failures(phone)
        self.stdout.write('superuser ensured')
