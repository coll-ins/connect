"""One check for every place that puts a bus on a trip or a schedule."""
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
