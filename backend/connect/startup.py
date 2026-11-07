"""Work the server does as it starts, whatever start command the host uses."""
import logging
import os

from django.core.management import call_command

log = logging.getLogger(__name__)


def ensure_platform_admin():
    """Create or repair the platform admin from ADMIN_PHONE / ADMIN_PASSWORD.

    Hosts such as Render use the start command from their own settings, not
    the repository's procfile, so this cannot rely on that command. A failure
    here must never stop the server from starting.
    """
    if not os.environ.get('ADMIN_PHONE') or not os.environ.get('ADMIN_PASSWORD'):
        return
    try:
        call_command('ensure_superuser')
    except Exception:
        log.exception('superuser not ensured')
