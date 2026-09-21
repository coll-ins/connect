# Africa's Talking SMS integration placeholder
import africastalking
from django.conf import settings

def get_sms():
    if not settings.AT_API_KEY:
        return None
    africastalking.initialize(
        username=settings.AT_USERNAME,
        api_key=settings.AT_API_KEY
    )
    return africastalking.SMS

def format_number(phone):
    phone = phone.strip().replace(' ', '')
    if phone.startswith('0'):
        return '+254' + phone[1:]
    if not phone.startswith('+'):
        return '+254' + phone
    return phone

def send_booking_sms(phone_number, booking_number):
    try:
        sms = get_sms()
        if sms is None:
            return False
        message = (
            f"Connect App: Booking confirmed!\n"
            f"Your booking number is: {booking_number}\n"
            f"We will send your driver details shortly."
        )
        sms.send(message, [format_number(phone_number)])
        return True
    except Exception as e:
        print(f"SMS failed: {e}")

def send_driver_sms(phone_number, booking_number, driver_name, driver_phone, bus_number):
    try:
        sms = get_sms()
        if sms is None:
            return False
        message = (
            f"Connect App: Booking {booking_number} confirmed!\n"
            f"Driver: {driver_name}\n"
            f"Bus: {bus_number}\n"
            f"Call driver: {driver_phone}\n"
            f"Safe journey!"
        )
        sms.send(message, [format_number(phone_number)])
        return True
    except Exception as e:
        print(f"SMS failed: {e}")

        sms.send(message, [format_number(phone_number)])
        return True
    except Exception as e:
        print(f"SMS failed: {e}")


def send_admin_alert_sms(message):
    """
    Send an alert SMS to all configured admin phone numbers.
    """
    numbers = getattr(settings, 'ADMIN_ALERT_PHONE_NUMBERS', [])

    if not numbers:
        return False

    try:
        sms = get_sms()

        if sms is None:
            return False

        sms.send(
            f"CONNECT ALERT: {message}",
            [format_number(number) for number in numbers]
        )

        return True

    except Exception as e:
        print(f"Admin alert SMS failed: {e}")
        return False