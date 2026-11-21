import logging

logger = logging.getLogger(__name__)


def send(message):
    """Log and SMS the admins about money that needs a human. Never raises."""
    logger.error('Wallet alert: %s', message)
    try:
        from notifications.sms import send_admin_alert_sms
        send_admin_alert_sms(message)
    except Exception:
        logger.exception('Admin alert failed: %s', message)
