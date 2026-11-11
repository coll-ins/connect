from django.db import migrations
from django.db.models import F

# City Shuttle's Kamangu buses load at the Kenya National Archives (Tom Mboya St),
# not at Kencom. Position: OpenStreetMap, "Kenya National Archives, Tom Mboya Street".
# The trip boards within 150 m of the first stage, which covers both fronts of the building.
NAME, LAT, LNG = 'Archives', '-1.284989', '36.825949'
ENDS = {'CBD to Kamangu': 'first', 'Kamangu to CBD': 'last'}


def install(apps, schema_editor):
    """Add Archives as the terminus of City Shuttle's Kamangu pair; every other stage stays."""
    Route = apps.get_model('companies', 'Route')
    PickupStage = apps.get_model('companies', 'PickupStage')
    for route in Route.objects.filter(company__name='CityShuttle', name__in=ENDS):
        stages = PickupStage.objects.filter(route=route)
        if stages.filter(name=NAME).exists():
            continue
        if ENDS[route.name] == 'first':
            stages.update(order=F('order') + 1)
            order = 1
            route.start_latitude, route.start_longitude = LAT, LNG
        else:
            order = max(stages.values_list('order', flat=True), default=0) + 1
            route.end_latitude, route.end_longitude = LAT, LNG
        PickupStage.objects.create(route=route, name=NAME, latitude=LAT, longitude=LNG,
                                   order=order, is_active=True, source='manual')
        route.save(update_fields=['start_latitude', 'start_longitude', 'end_latitude', 'end_longitude'])


class Migration(migrations.Migration):
    dependencies = [('companies', '0021_city_shuttle_kamangu')]

    operations = [migrations.RunPython(install, migrations.RunPython.noop)]
