from django.db import migrations


def backfill(apps, schema_editor):
    Trip = apps.get_model('companies', 'Trip')
    Booking = apps.get_model('bookings', 'Booking')
    SeatAssignment = apps.get_model('bookings', 'SeatAssignment')
    for trip in Trip.objects.filter(status__in=['scheduled', 'boarding']).iterator():
        taken = set(SeatAssignment.objects.filter(trip=trip).values_list('seat_no', flat=True))
        free = (s for s in range(1, trip.capacity + 1) if s not in taken)
        rows = []
        live = (
            Booking.objects.filter(trip=trip, status__in=['pending', 'confirmed'])
            .exclude(seat_assignments__isnull=False).order_by('created_at', 'id')
        )
        for b in live:
            for _ in range(b.seats):
                no = next(free, None)
                if no is None:
                    break
                rows.append(SeatAssignment(trip=trip, seat_no=no, booking=b))
        SeatAssignment.objects.bulk_create(rows)


class Migration(migrations.Migration):
    dependencies = [('bookings', '0026_seatassignment')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
