"""One check for every place that puts a bus on a trip or a schedule."""
import re

from django.db import IntegrityError, transaction
from django.db.models import Q

from bookings.seats import VEHICLES
from buses.models import Bus

ACTIVE_TRIP = ('scheduled', 'boarding', 'departed')


def lock_bus(bus_id, company, departure_at=None, exclude_trip_id=None):
    """Lock and return (bus, None), or (None, error). Call inside atomic().
    The row lock stops two trips claiming the same bus at the same moment."""
    # Whole numbers only: int(2.5) would quietly pick bus 2.
    if isinstance(bus_id, bool) or not str(bus_id).strip().isdigit():
        return None, 'Pick one of your company\'s buses.'
    try:
        bus = Bus.objects.select_for_update().get(id=int(str(bus_id).strip()), company=company)
    except Bus.DoesNotExist:
        return None, 'Pick one of your company\'s buses.'
    if not bus.is_active or bus.maintenance_status != 'operational':
        return None, f'Bus {bus.bus_number} ({bus.registration_number}) is not in service.'
    if departure_at is not None:
        clash = bus.trips.filter(departure_at=departure_at, status__in=ACTIVE_TRIP)
        if exclude_trip_id:
            clash = clash.exclude(id=exclude_trip_id)
        if clash.exists():
            return None, (
                f'Bus {bus.bus_number} ({bus.registration_number}) already runs a trip '
                'at that time. Pick another bus.'
            )
    return bus, None


def driver_bus(driver, vehicle_type):
    """Return (bus, None) or (None, error): the driver's own bus as the
    chosen vehicle type. Found by the driver's fleet number or plate, made
    on first use. Call inside atomic() with the driver row locked, and roll
    back if the request fails afterwards (a retype is saved here)."""
    if not isinstance(vehicle_type, str) or vehicle_type not in VEHICLES:
        return None, 'Pick a vehicle type.'
    number = (driver.bus_number or '').strip()
    compact = ''.join(number.upper().split())
    plate = (f'{compact[:3]} {compact[3:]}'
             if re.fullmatch(r'(K[A-Z]{2}|EV[A-Z])\d{3}[A-Z]', compact) else None)
    match = Q(bus_number__iexact=number) if number else Q(pk__in=[])
    if plate:
        match |= Q(registration_number=plate)
    bus = Bus.objects.select_for_update().filter(match, company=driver.company_id).first()
    label = VEHICLES[vehicle_type]['label']
    if bus:
        if bus.vehicle_type != vehicle_type:
            if (bus.trips.filter(status__in=ACTIVE_TRIP).exists()
                    or bus.trip_schedules.filter(is_active=True).exists()):
                return None, (
                    f'{driver.name}\'s bus {bus.bus_number} is a {bus.get_vehicle_type_display()} '
                    'and has trips or a service template on it. Pick that type, or another driver.'
                )
            bus.vehicle_type = vehicle_type
            bus.save()
        return bus, None
    if not plate:
        return None, (
            f'{driver.name}\'s bus "{number or "none"}" has no number plate on file. '
            'Add it once under Buses & seats, then create the trip.'
        )
    try:
        with transaction.atomic():
            bus = Bus.objects.create(
                company_id=driver.company_id, registration_number=plate,
                bus_number=number, vehicle_type=vehicle_type,
                capacity=VEHICLES[vehicle_type]['seats'],
            )
    except IntegrityError:
        return None, (
            f'Plate {plate} or fleet number {number} is already registered to another bus. '
            'Check the driver\'s bus under Buses & seats.'
        )
    return bus, None
