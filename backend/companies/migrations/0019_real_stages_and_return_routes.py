import json
from pathlib import Path

from django.db import migrations

# Built by tools/build_route_network.py from OpenStreetMap roads and stops.
DATA = Path(__file__).resolve().parent.parent / 'data' / 'route_network.json'


def _nearest(stage, choices):
    return min(choices, key=lambda c: (
        (float(c.latitude) - float(stage.latitude)) ** 2
        + (float(c.longitude) - float(stage.longitude)) ** 2
    ))


def install(apps, schema_editor):
    Company = apps.get_model('companies', 'Company')
    Route = apps.get_model('companies', 'Route')
    PickupStage = apps.get_model('companies', 'PickupStage')
    Booking = apps.get_model('bookings', 'Booking')
    Parcel = apps.get_model('deliveries', 'Parcel')
    open_trip = ('scheduled', 'boarding', 'departed')
    companies = {c.name: c for c in Company.objects.all()}
    outbound = None

    # Entries come in pairs: a route, then the same road back.
    for index, item in enumerate(json.loads(DATA.read_text(encoding='utf-8'))):
        if index % 2 == 0:
            outbound = None
        company = companies.get(item['company'])
        if company is None:
            continue
        stages = item['stages']
        fields = {
            'start_point': item['start_point'],
            'end_point': item['end_point'],
            'start_latitude': stages[0][1],
            'start_longitude': stages[0][2],
            'end_latitude': stages[-1][1],
            'end_longitude': stages[-1][2],
            'geometry': {'type': 'LineString', 'coordinates': item['line']},
            'via_points': [],
        }
        route = Route.objects.filter(company=company, name=item['name']).order_by('id').first()
        if route is None:
            if index % 2 and outbound is not None:
                # The way back carries parcels at the same rates as the way out.
                fields.update(
                    price=outbound.price,
                    parcel_price_small=outbound.parcel_price_small,
                    parcel_price_medium=outbound.parcel_price_medium,
                    parcel_price_large=outbound.parcel_price_large,
                )
            else:
                fields['price'] = item['price']
            route = Route.objects.create(company=company, name=item['name'], **fields)
        else:
            Route.objects.filter(pk=route.pk).update(**fields)
        if index % 2 == 0:
            outbound = route

        # Old stages are switched off, not deleted: bookings and parcels point at them.
        PickupStage.objects.filter(route=route).update(is_active=False)
        for order, (name, lat, lng) in enumerate(stages, start=1):
            values = {'latitude': lat, 'longitude': lng, 'order': order, 'is_active': True}
            stage = PickupStage.objects.filter(route=route, name=name).order_by('id').first()
            if stage is None:
                PickupStage.objects.create(route=route, name=name, source='manual', **values)
            else:
                PickupStage.objects.filter(pk=stage.pk).update(**values)

        # Riders and parcels already booked at a stage that is now off move to
        # the nearest new one, so the driver still sees them at a stage.
        new = list(PickupStage.objects.filter(route=route, is_active=True).order_by('order', 'id'))
        for old in PickupStage.objects.filter(route=route, is_active=False):
            board = _nearest(old, new[:-1])
            Booking.objects.filter(
                pickup_stage=old, trip__status__in=open_trip,
                status__in=('pending', 'confirmed'),
            ).update(pickup_stage=board, pickup_location=board.name)
            live = Parcel.objects.filter(
                trip__status__in=open_trip, status__in=('pending_payment', 'paid', 'picked_up'))
            live.filter(pickup_stage=old).update(pickup_stage=board)
            for parcel in live.filter(dropoff_stage=old).select_related('pickup_stage'):
                after = [s for s in new if s.order > parcel.pickup_stage.order] or new[-1:]
                Parcel.objects.filter(pk=parcel.pk).update(dropoff_stage=_nearest(old, after))


class Migration(migrations.Migration):
    dependencies = [
        ('companies', '0018_trip_bus_tripschedule_bus'),
        ('bookings', '0027_backfill_seats'),
        ('deliveries', '0001_initial'),
    ]

    operations = [migrations.RunPython(install, migrations.RunPython.noop)]
