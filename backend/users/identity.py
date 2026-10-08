"""Who counts as a driver's login account. One definition, used everywhere."""
from .phone import KENYA_MOBILE, canonical_phone


def _phone(value):
    """Canonical phone, or None for blank/missing (a blank phone must never match)."""
    return canonical_phone(value) or None


def is_driver_account_for(user, driver):
    """
    True only when `user` is the login account of `driver`:
      * the user has the driver role;
      * both have a phone number and the numbers are equal in canonical form;
      * if the user belongs to a company, it is the driver's company.
    """
    if user is None or driver is None:
        return False
    if getattr(user, 'role', None) != 'driver':
        return False
    user_phone = _phone(getattr(user, 'phone_number', None))
    driver_phone = _phone(getattr(driver, 'phone_number', None))
    if not user_phone or user_phone != driver_phone:
        return False
    company_id = getattr(user, 'company_id', None)
    return company_id is None or company_id == getattr(driver, 'company_id', None)


def drivers_for_user(user):
    """Driver rows this user is the login account of. A blank phone matches nothing."""
    from drivers.models import Driver

    phone = _phone(getattr(user, 'phone_number', None))
    if not phone:
        return Driver.objects.none()
    variants = {phone, str(user.phone_number).strip()}
    if KENYA_MOBILE.match(phone):
        variants.update({'0' + phone[4:], phone[1:]})     # legacy 07... and 2547... rows
    queryset = Driver.objects.filter(phone_number__in=variants)
    company_id = getattr(user, 'company_id', None)
    if company_id is not None:
        queryset = queryset.filter(company_id=company_id)
    return queryset
