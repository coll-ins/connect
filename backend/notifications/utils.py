# Notification helpers placeholder
def format_phone_number(phone):
    phone = phone.strip()
    if phone.startswith('0'):
        phone = '+254' + phone[1:]
    elif not phone.startswith('+'):
        phone = '+254' + phone
    return phone