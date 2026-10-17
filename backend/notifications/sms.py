"""Africa's Talking SMS helpers. These never raise: they run inside payment flows."""
import logging

import africastalking
from django.conf import settings

logger = logging.getLogger(__name__)


def get_sms():
    if not settings.AT_API_KEY:
        return None
    africastalking.initialize(
        username=settings.AT_USERNAME,
        api_key=settings.AT_API_KEY,
    )
    return africastalking.SMS


def format_number(phone):
    phone = phone.strip().replace(' ', '')
    if phone.startswith('0'):
        return '+254' + phone[1:]
    if not phone.startswith('+'):
        return '+254' + phone
    return phone


def _send(message, phones, label):
    try:
        sms = get_sms()
        if sms is None:
            logger.warning('SMS not sent (%s): AT_API_KEY is not configured.', label)
            return False
        sms.send(message, [format_number(p) for p in phones])
        return True
    except Exception:
        logger.exception('SMS failed (%s)', label)
        return False


def send_booking_sms(phone_number, booking_number):
    message = (
        f"Connect App: Booking confirmed!\n"
        f"Your booking number is: {booking_number}\n"
        f"We will send your driver details shortly."
    )
    return _send(message, [phone_number], 'booking')


def send_driver_sms(phone_number, booking_number, driver_name, driver_phone, bus_number):
    message = (
        f"Connect App: Booking {booking_number} confirmed!\n"
        f"Driver: {driver_name}\n"
        f"Bus: {bus_number}\n"
        f"Call driver: {driver_phone}\n"
        f"Safe journey!"
    )
    return _send(message, [phone_number], 'driver')


def send_admin_alert_sms(message):
    """Send an alert SMS to all configured admin phone numbers."""
    numbers = getattr(settings, 'ADMIN_ALERT_PHONE_NUMBERS', [])
    if not numbers:
        logger.error('Admin alert not sent (no ADMIN_ALERT_PHONE_NUMBERS): %s', message)
        return False
    return _send(f"CONNECT ALERT: {message}", numbers, 'admin-alert')


def send_departure_sms(phone_number, booking_number, route_name):
    message = (
        f"Connect App: Your bus for {route_name} has left the stage.\n"
        f"Booking {booking_number}. Open Live Map in the app to track it."
    )
    return _send(message, [phone_number], 'departure')
