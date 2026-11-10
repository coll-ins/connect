import json
from pathlib import Path

from django.db import migrations

DATA = Path(__file__).resolve().parent.parent / 'data' / 'route_network.json'
NAMES = {'CBD to Kamangu', 'Kamangu to CBD'}


def install(apps, schema_editor):
    """Add City Shuttle's Kamangu pair only; other routes and manager edits are untouched."""
    Company = apps.get_model('companies', 'Company')
    Route = apps.get_model('companies', 'Route')
    PickupStage = apps.get_model('companies', 'PickupStage')
    company = Company.objects.filter(name='CityShuttle').order_by('id').first()
    if company is None:
        return
    for item in json.loads(DATA.read_text(encoding='utf-8')):
        if item['company'] != 'CityShuttle' or item['name'] not in NAMES:
            continue
        if Route.objects.filter(company=company, name=item['name']).exists():
            continue
        stages = item['stages']
        route = Route.objects.create(
            company=company, name=item['name'], price=item['price'],
            start_point=item['start_point'], end_point=item['end_point'],
            start_latitude=stages[0][1], start_longitude=stages[0][2],
            end_latitude=stages[-1][1], end_longitude=stages[-1][2],
            geometry={'type': 'LineString', 'coordinates': item['line']},
            via_points=[],
        )
        for order, (name, lat, lng) in enumerate(stages, start=1):
            PickupStage.objects.create(
                route=route, name=name, latitude=lat, longitude=lng,
                order=order, is_active=True, source='manual',
            )


class Migration(migrations.Migration):
    dependencies = [('companies', '0020_long_distance_town_stages')]

    operations = [migrations.RunPython(install, migrations.RunPython.noop)]
