import json
from pathlib import Path

from django.db import migrations

DATA = Path(__file__).resolve().parent.parent / 'data' / 'route_network.json'

# Long-distance routes got their town stages (Naivasha, Nakuru, Kericho...)
# and a line on the A104/B1 highway. Only these routes are touched, so stage
# changes managers made on city routes since 0019 are kept.
LONG = {'Nairobi to Kisumu', 'Kisumu to Nairobi', 'Nairobi to Kakamega',
        'Kakamega to Nairobi', 'Nairobi to Nakuru', 'Nakuru to Nairobi'}


def _nearest(stage, choices):
    return min(choices, key=lambda c: (
        (float(c.latitude) - float(stage.latitude)) ** 2
        + (float(c.longitude) - float(stage.longitude)) ** 2
    ))


def install(apps, schema_editor):
    Route = apps.get_model('companies', 'Route')
    PickupStage = apps.get_model('companies', 'PickupStage')
    Booking = apps.get_model('bookings', 'Booking')
    Parcel = apps.get_model('deliveries', 'Parcel')
    open_trip = ('scheduled', 'boarding', 'departed')

    for item in json.loads(DATA.read_text(encoding='utf-8')):
        if item['name'] not in LONG:
            continue
        route = Route.objects.filter(
            company__name=item['company'], name=item['name']).order_by('id').first()
        if route is None:
            continue
        stages = item['stages']
        Route.objects.filter(pk=route.pk).update(
            start_latitude=stages[0][1], start_longitude=stages[0][2],
            end_latitude=stages[-1][1], end_longitude=stages[-1][2],
            geometry={'type': 'LineString', 'coordinates': item['line']},
            via_points=[],
        )
        before = set(PickupStage.objects.filter(route=route, is_active=True).values_list('id', flat=True))
        PickupStage.objects.filter(route=route).update(is_active=False)
        for order, (name, lat, lng) in enumerate(stages, start=1):
            values = {'latitude': lat, 'longitude': lng, 'order': order, 'is_active': True}
            stage = PickupStage.objects.filter(route=route, name=name).order_by('id').first()
            if stage is None:
                PickupStage.objects.create(route=route, name=name, source='manual', **values)
            else:
                PickupStage.objects.filter(pk=stage.pk).update(**values)
        # Riders and parcels booked at a stage that just went off move to the
        # nearest new one, so the driver still sees them at a stage.
        new = list(PickupStage.objects.filter(route=route, is_active=True).order_by('order', 'id'))
        for old in PickupStage.objects.filter(route=route, is_active=False, id__in=before):
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
    dependencies = [('companies', '0019_real_stages_and_return_routes')]
    operations = [migrations.RunPython(install, migrations.RunPython.noop)]
