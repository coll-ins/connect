"""
Seat maps drawn as the real vehicles Kenyan operators run, picked by capacity.
Seen from above, front at the top. Kenya drives on the left: the driver ('D')
sits front right and passengers board on the left ('door').
  14  Toyota HiAce matatu: 2 beside the driver, sliding door on the left
      beside row 2, rows of 3 with no aisle (the door-side seat folds),
      back bench of 3.
  29  Rosa/Liesse minibus: door front left, 2+2 with an aisle, back row of 5.
  33  Isuzu NQR minibus: door front left, 2+2 with an aisle, back row of 5.
  51  Coach: door front left, 2 seats behind the driver, 2+2, back row of 5.
  anything else: the same 2+2 bus plan, filled to its capacity.
Every row has the same number of columns. Cells: seat number, None (aisle or
empty floor), 'D' driver, 'door'.

Every function that writes assumes the caller holds the Trip row lock
(select_for_update), like the rest of the booking code.
"""
from django.db.models import Q, Sum

AISLE = None


def layout_for(capacity):
    n = 0

    def seats(k):
        nonlocal n
        row = list(range(n + 1, n + k + 1))
        n += k
        return row

    if capacity == 14:
        # First column is the left wall: the sliding door opens beside row 2.
        rows = [[AISLE] + seats(2) + ['D'], ['door'] + seats(3)]
        rows += [[AISLE] + seats(3) for _ in range(3)]
        return rows

    # Buses: 5 columns = 2 seats, aisle, 2 seats; the back bench spans the
    # aisle. Seats that don't fill a 2+2 row sit behind the driver, opposite
    # the door, as on real coaches (a 51-seater: 2 there, 11 rows, bench of 5).
    rows = [['door', AISLE, AISLE, AISLE, 'D']]
    if capacity < 5:
        rows.append(seats(capacity) + [AISLE] * (5 - capacity))
        return rows
    extra = (capacity - 5) % 4
    if extra:
        front = seats(extra)
        rows.append(['door'] + [AISLE] * (4 - extra) + front)
    while capacity - n > 5:
        rows.append(seats(2) + [AISLE] + seats(2))
    rows.append(seats(5))
    return rows


def _active():
    # Seats held by a cancelled booking are free again; no cancel path has
    # to remember to delete them.
    return Q(blocked=True) | Q(booking__isnull=False) & ~Q(booking__status='cancelled')


def seats_taken(trip):
    """Seats no longer sellable: every live booking's seat count plus blocks."""
    booked = (
        trip.bookings.exclude(status='cancelled')
        .aggregate(total=Sum('seats'))['total'] or 0
    )
    return booked + trip.seat_assignments.filter(blocked=True).count()


def occupied_numbers(trip):
    return set(trip.seat_assignments.filter(_active()).values_list('seat_no', flat=True))


class SeatError(ValueError):
    pass


def assign_seats(trip, booking, wanted=None):
    """Give `booking` booking.seats seats on `trip`: the `wanted` numbers if
    given and free, else the lowest free ones. Returns the numbers."""
    from .models import SeatAssignment

    trip.seat_assignments.filter(booking__status='cancelled').delete()
    trip.seat_assignments.filter(booking=booking).delete()
    taken = occupied_numbers(trip)
    count = booking.seats

    if wanted:
        if not isinstance(wanted, (list, tuple)):
            raise SeatError('Seat numbers must be a list.')
        try:
            wanted = [int(x) for x in wanted]
        except (TypeError, ValueError):
            raise SeatError('Seat numbers must be whole numbers.')
        if len(wanted) != count or len(set(wanted)) != count:
            raise SeatError(f'Pick exactly {count} different seat(s).')
        bad = [s for s in wanted if not 1 <= s <= trip.capacity]
        if bad:
            raise SeatError(f'Seat {bad[0]} does not exist on this bus.')
        clash = sorted(set(wanted) & taken)
        if clash:
            raise SeatError(f'Seat {clash[0]} was just taken. Pick another.')
        numbers = wanted
    else:
        free = [s for s in range(1, trip.capacity + 1) if s not in taken]
        # Not enough numbered seats left (older bookings without numbers):
        # give what exists; the count check already guaranteed capacity.
        numbers = free[:count]

    SeatAssignment.objects.bulk_create(
        [SeatAssignment(trip=trip, seat_no=s, booking=booking) for s in numbers]
    )
    return numbers


def move_seats(old_trip, new_trip, booking):
    """Moving bus: keep the same seat numbers when they are free there."""
    keep = list(
        booking.seat_assignments.filter(trip=old_trip)
        .values_list('seat_no', flat=True)
    )
    booking.seat_assignments.filter(trip=old_trip).delete()
    new_trip.seat_assignments.filter(booking__status='cancelled').delete()
    free_there = not (set(keep) & occupied_numbers(new_trip))
    if keep and len(keep) == booking.seats and free_there and max(keep) <= new_trip.capacity:
        return assign_seats(new_trip, booking, keep)
    return assign_seats(new_trip, booking)


def seat_map(trip, viewer_booking_ids=(), show_names=False):
    rows = (
        trip.seat_assignments.filter(_active())
        .select_related('booking__user', 'booking__boarding_event')
    )
    by_no = {}
    for a in rows:
        if a.blocked:
            item = {'state': 'blocked'}
            if show_names:  # staff notes ("VIP", names) are not for passengers
                item['note'] = a.note
        else:
            b = a.booking
            boarded = b.status == 'completed' or hasattr(b, 'boarding_event')
            state = 'boarded' if boarded else ('booked' if b.status == 'confirmed' else 'held')
            item = {'state': state, 'mine': b.id in viewer_booking_ids}
            if show_names:
                item['booking_number'] = b.booking_number
                item['passenger'] = (b.user.first_name or b.user.display_name)
        by_no[a.seat_no] = item

    seats = [{'no': no, **by_no.get(no, {'state': 'free'})} for no in range(1, trip.capacity + 1)]
    numbered = sum(1 for a in rows if not a.blocked)
    live_seats = (
        trip.bookings.exclude(status='cancelled')
        .aggregate(total=Sum('seats'))['total'] or 0
    )
    return {
        'trip_id': trip.id,
        'capacity': trip.capacity,
        'layout': layout_for(trip.capacity),
        'seats': seats,
        # Seats sold before seat numbers existed: real but not on the map.
        'unassigned': max(0, live_seats - numbered),
    }
