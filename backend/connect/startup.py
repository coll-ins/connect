"""Work the server does as it starts, whatever start command the host uses."""
import logging
import os

from django.core.management import call_command

log = logging.getLogger(__name__)

# What happened when this server started. /api/health/ shows it, so a failed
# admin setup can be seen without opening the host's logs. Codes only.
admin_setup = 'not_configured'


def ensure_platform_admin():
    """Create or repair the platform admin from ADMIN_PHONE / ADMIN_PASSWORD.

    Hosts such as Render use the start command from their own settings, not
    the repository's procfile, so this cannot rely on that command. A failure
    here must never stop the server from starting.
    """
    global admin_setup
    if not os.environ.get('ADMIN_PHONE') or not os.environ.get('ADMIN_PASSWORD'):
        admin_setup = 'not_configured'
        return
    from users.management.commands.ensure_superuser import Command

    command = Command()
    try:
        call_command(command)
        admin_setup = command.outcome
    except Exception:
        admin_setup = 'failed'
        log.exception('superuser not ensured')
