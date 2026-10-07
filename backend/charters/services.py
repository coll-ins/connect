import re
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from companies.models import Company
from drivers.models import Driver
from users.permissions import can_manage_company
from users.views import normalize_phone_number

from .models import CharterRequest

MIN_LEAD = timedelta(hours=24)
MAX_TRIP_LENGTH = timedelta(days=14)
MAX_OPEN_REQUESTS = 5
MAX_PASSENGERS = 200
MAX_PRICE = Decimal('1000000.00')


class CharterError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def create_charter(*, passenger, company_id, purpose, pickup_location, destination,
                   depart_at, return_at, passenger_count, contact_name,
                   contact_phone, notes):
    company = Company.objects.filter(id=company_id, accepts_charters=True).first()
    if company is None:
        raise CharterError('This company does not accept bus hire requests.', 404)

    now = timezone.now()
    if depart_at < now + MIN_LEAD:
        raise CharterError('Departure must be at least 24 hours from now.')
    if return_at is not None:
        if return_at <= depart_at:
            raise CharterError('Return time must be after departure.')
        if return_at - depart_at > MAX_TRIP_LENGTH:
            raise CharterError('A hire cannot be longer than 14 days.')
    if not 1 <= passenger_count <= MAX_PASSENGERS:
        raise CharterError(f'Passenger count must be between 1 and {MAX_PASSENGERS}.')

    phone = normalize_phone_number(contact_phone)
    if not re.fullmatch(r'\+254\d{9}', phone or ''):
        raise CharterError('Enter a valid Kenyan contact phone number.')

    open_count = CharterRequest.objects.filter(
        passenger=passenger, status__in=['requested', 'quoted']).count()
    if open_count >= MAX_OPEN_REQUESTS:
        raise CharterError('Too many open requests. Cancel or finish some first.', 429)

    return CharterRequest.objects.create(
        passenger=passenger, company=company,
        purpose=purpose.strip(), pickup_location=pickup_location.strip(),
        destination=destination.strip(), depart_at=depart_at, return_at=return_at,
        passenger_count=passenger_count, contact_name=contact_name.strip(),
        contact_phone=phone, notes=notes.strip(),
    )


def _lock_driver_and_check(driver_id, charter):
    """Lock the driver row so two payments cannot both claim the same window."""
    driver = Driver.objects.select_for_update().get(id=driver_id)
    start, end = charter.depart_at, charter.end_at()
    others = CharterRequest.objects.filter(driver=driver, status='confirmed').exclude(id=charter.id)
    for other in others:
        if start < other.end_at() and end > other.depart_at:
            raise CharterError('That bus is already booked for those dates.', 409)
    return driver


def quote_charter(*, charter_id, manager, price, driver_id, valid_hours):
    with transaction.atomic():
        charter = CharterRequest.objects.select_for_update().get(id=charter_id)
        if not can_manage_company(manager, charter.company_id):
            raise CharterError('Only a manager of this company can quote.', 403)
        if charter.status not in ('requested', 'quoted'):
            raise CharterError('This request can no longer be quoted.', 409)
        if charter.depart_at <= timezone.now():
            raise CharterError('The departure time has already passed.', 409)

        price = Decimal(str(price)).quantize(Decimal('0.01'))
        if price <= 0 or price > MAX_PRICE:
            raise CharterError('Enter a valid price.')
        if not 1 <= valid_hours <= 168:
            raise CharterError('A quote can be valid for 1 to 168 hours.')

        driver = Driver.objects.filter(id=driver_id, company_id=charter.company_id).first()
        if driver is None:
            raise CharterError('Choose a driver from this company.')
        _lock_driver_and_check(driver.id, charter)

        charter.driver = driver
        charter.quote_price = price
        charter.quote_valid_until = timezone.now() + timedelta(hours=valid_hours)
        charter.status = 'quoted'
        charter.decline_reason = ''
        charter.save()
        return charter


def decline_charter(*, charter_id, manager, reason):
    reason = (reason or '').strip()
    if not reason or len(reason) > 300:
        raise CharterError('Give a reason (up to 300 characters).')
    with transaction.atomic():
        charter = CharterRequest.objects.select_for_update().get(id=charter_id)
        if not can_manage_company(manager, charter.company_id):
            raise CharterError('Only a manager of this company can decline.', 403)
        if charter.status not in ('requested', 'quoted'):
            raise CharterError('This request can no longer be declined.', 409)
        charter.status = 'declined'
        charter.decline_reason = reason
        charter.save(update_fields=['status', 'decline_reason', 'updated_at'])
        return charter


def cancel_charter(*, charter_id, user):
    with transaction.atomic():
        charter = CharterRequest.objects.select_for_update().get(id=charter_id)
        if charter.passenger_id != user.id:
            raise CharterRequest.DoesNotExist
        if charter.status in ('requested', 'quoted'):
            charter.status = 'cancelled'
            charter.cancelled_at = timezone.now()
            charter.save(update_fields=['status', 'cancelled_at', 'updated_at'])
            return charter
        if charter.status == 'confirmed':
            raise CharterError(
                'This hire is already paid. Refunds are not automated yet; contact support.', 409)
        raise CharterError('This request can no longer be cancelled.', 409)


def mark_charter_paid(*, charter_id, amount, reference):
    """Called ONLY by the payment-confirmation path. Returns (charter, changed)."""
    with transaction.atomic():
        charter = CharterRequest.objects.select_for_update().get(id=charter_id)
        if charter.status == 'confirmed' and charter.provider_reference == reference:
            return charter, False
        if charter.status != 'quoted':
            raise CharterError('This request is not awaiting payment.', 409)
        if charter.effective_status() == 'expired':
            raise CharterError('This quote has expired.', 409)
        if charter.depart_at <= timezone.now():
            raise CharterError('The departure time has already passed.', 409)
        if Decimal(str(amount)) != charter.quote_price:
            raise CharterError('Paid amount does not match the quote.', 409)
        _lock_driver_and_check(charter.driver_id, charter)
        charter.status = 'confirmed'
        charter.provider_reference = reference
        charter.paid_at = timezone.now()
        charter.save(update_fields=['status', 'provider_reference', 'paid_at', 'updated_at'])
        return charter, True


def complete_charter(*, charter_id):
    with transaction.atomic():
        charter = CharterRequest.objects.select_for_update().get(id=charter_id)
        if charter.status != 'confirmed':
            raise CharterError('Only confirmed hires can be completed.', 409)
        if charter.depart_at > timezone.now():
            raise CharterError('This hire has not started yet.', 409)
        charter.status = 'completed'
        charter.completed_at = timezone.now()
        charter.save(update_fields=['status', 'completed_at', 'updated_at'])
        return charter


def check_payable(*, charter_id, user):
    """Everything that must be true before taking money for a quote."""
    with transaction.atomic():
        charter = CharterRequest.objects.select_for_update().get(id=charter_id)
        if charter.passenger_id != user.id:
            raise CharterRequest.DoesNotExist
        if charter.status != 'quoted':
            raise CharterError('This request is not awaiting payment.', 409)
        if charter.effective_status() == 'expired':
            raise CharterError('This quote has expired. Ask the company for a new one.', 409)
        if charter.depart_at <= timezone.now():
            raise CharterError('The departure time has already passed.', 409)
        _lock_driver_and_check(charter.driver_id, charter)
        return charter


def set_pending_reference(*, charter_id, reference):
    CharterRequest.objects.filter(id=charter_id, status='quoted').update(
        provider_reference=reference)
