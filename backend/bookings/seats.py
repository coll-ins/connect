"""
Seat maps of real vehicles, seen from above, front at the top. Kenya drives on
the left: the driver ('D') sits front right, passengers board on the left.
Cells: seat number, None (aisle or empty floor), 'D' driver, 'door'.

VEHICLES holds only plans copied from a published diagram (source on each).
The ACMG drawings are right-hand drive with numbered seats; their numbers are
kept as printed. Toyota publishes the HiAce plan for left-hand drive without
numbers, so it is mirrored and numbered front to back, left to right.
A bus whose plan is not published ('other') gets a plain 2+2 plan sized to
its seat count, and the app says the plan is not verified.

Every function that writes assumes the caller holds the Trip row lock
(select_for_update), like the rest of the booking code.
"""
import random

from django.db.models import Q, Sum

AISLE = None
_ = AISLE


def _rows(first, last_row_start, left=2, right=3):
    """Repeating rows after the door: `left` seats, aisle, `right` seats."""
    out, n = [], first
    while n < last_row_start:
        out.append(list(range(n, n + left)) + [_] + list(range(n + left, n + left + right)))
        n += left + right
    return out


VEHICLES = {
    'matatu_14': {
        'label': '14-seater matatu (Toyota HiAce Commuter)',
        'seats': 14,
        # https://global.toyota/en/newsroom/toyota/26716528.html Commuter No. 6
        # (capacity 15 = driver + 14): 2 beside the driver, a bench of 3 by the
        # sliding door, then 3 rows of 1 + aisle + 2.
        'layout': [
            [1, 2, _, 'D'],
            ['door', 3, 4, 5],
            [6, _, 7, 8],
            [9, _, 10, 11],
            [12, _, 13, 14],
        ],
    },
    'minibus_27': {
        'label': '27-seater minibus (Isuzu NMR85)',
        'seats': 27,
        # https://www.acmgl.com/isuzu/bus/nmr85 seat layout drawing (2+2, door
        # behind the first row, back row of 5).
        'layout': [
            [2, 1, _, _, 'D'],
            [6, 5, _, 4, 3],
            ['door', 'door', _, 8, 7],
            [12, 11, _, 10, 9],
            [16, 15, _, 14, 13],
            [_, _, _, 18, 17],
            [20, 19, _, 22, 21],
            [27, 26, 25, 24, 23],
        ],
    },
    'minibus_33': {
        'label': '33-seater minibus (Isuzu NQR81M)',
        'seats': 33,
        # Seat count, length 7,815 mm and the 2 seats beside the driver
        # ("Driver & Assistant Seat ... Centre Seat") are from Isuzu East
        # Africa's N-series brochure (isuzu.co.ke). No 33-seat drawing is
        # published, so the rows follow the same maker's 27-seat drawing above,
        # two rows longer; seat positions are approximate.
        'verified': False,
        'layout': [
            [2, 1, _, _, 'D'],
            [6, 5, _, 4, 3],
            ['door', 'door', _, 8, 7],
        ] + [
            [n + 3, n + 2, _, n + 1, n] for n in range(9, 26, 4)
        ] + [
            [33, 32, 31, 30, 29],
        ],
    },
    'bus_51': {
        'label': '51-seater bus (Isuzu FTR90)',
        'seats': 51,
        # https://www.acmgl.com/isuzu/bus/ftr90 seat layout drawing (3+2, the 3
        # on the driver side, back row of 6).
        'layout': [
            [2, 1, _, _, _, 'D'],
            [4, 3, _, 7, 6, 5],
            ['door', 'door', _, 10, 9, 8],
        ] + [
            [n + 4, n + 3, _, n + 2, n + 1, n] for n in range(11, 42, 5)
        ] + [
            [51, 50, 49, 48, 47, 46],
        ],
    },
    'bus_67': {
        'label': '67-seater bus (Isuzu FVR34S)',
        'seats': 67,
        # https://www.acmgl.com/isuzu/bus/fvr34s seat layout drawing (3+2, the 3
        # on the driver side, back row of 6; the drawing prints 28 as "38").
        'layout': [
            [1, _, _, _, _, 'D'],
            [2, 3, _, _, _, _],
            [4, 5, _, 8, 7, 6],
            ['door', 'door', _, 9, 10, 11],
        ] + _rows(12, 62) + [
            [62, 63, 64, 65, 66, 67],
        ],
    },
}
OTHER = 'other'


def _generic(capacity):
    """2+2 rows behind a front-left door, back bench of 5, numbered in order."""
    n = 0

    def seats(k):
        nonlocal n
        row = list(range(n + 1, n + k + 1))
        n += k
        return row

    rows = [['door', _, _, _, 'D']]
    if capacity < 5:
        rows.append(seats(capacity) + [_] * (5 - capacity))
        return rows
    extra = (capacity - 5) % 4
    if extra:
        rows.append(['door'] + [_] * (4 - extra) + seats(extra))
    while capacity - n > 5:
        rows.append(seats(2) + [_] + seats(2))
    rows.append(seats(5))
    return rows


def vehicle_for(capacity, vehicle_type=None):
    """The published plan for this bus type, else the one whose seat count
    matches (trips made before buses had a type), else None."""
    if vehicle_type in VEHICLES:
        return VEHICLES[vehicle_type]
    # Exact plans only: a bare seat count is not proof of the approximate one.
    if vehicle_type in (None, ''):
        for v in VEHICLES.values():
            if v['seats'] == capacity and v.get('verified', True):
                return v
    return None


def layout_for(capacity, vehicle_type=None):
    v = vehicle_for(capacity, vehicle_type)
    return v['layout'] if v else _generic(capacity)


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
        numbers = random.sample(free, min(count, len(free)))

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
    bus = trip.bus
    vehicle_type = bus.vehicle_type if bus else None
    vehicle = vehicle_for(trip.capacity, vehicle_type)
    return {
        'trip_id': trip.id,
        'capacity': trip.capacity,
        'bus': {
            'fleet_number': bus.bus_number,
            'plate': bus.registration_number,
            'vehicle_type': bus.vehicle_type,
        } if bus else None,
        'vehicle_label': vehicle['label'] if vehicle else f'{trip.capacity}-seater',
        # False: seat positions are approximate, the seat numbers still hold.
        'plan_verified': bool(vehicle and vehicle.get('verified', True)),
        'driver_name': trip.driver.name,
        'layout': vehicle['layout'] if vehicle else _generic(trip.capacity),
        'seats': seats,
        # Seats sold before seat numbers existed: real but not on the map.
        'unassigned': max(0, live_seats - numbered),
    }
