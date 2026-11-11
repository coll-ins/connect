from django.db import migrations

# 0022 made Archives the terminus; draw the road line from there too.
POINT = [36.825949, -1.284989]  # [lng, lat], same spot as the Archives stage


def extend(apps, schema_editor):
    Route = apps.get_model('companies', 'Route')
    for route in Route.objects.filter(company__name='CityShuttle',
                                      name__in=('CBD to Kamangu', 'Kamangu to CBD')):
        geometry = route.geometry if isinstance(route.geometry, dict) else None
        line = geometry.get('coordinates') if geometry and geometry.get('type') == 'LineString' else None
        if not line or POINT in line:
            continue
        geometry['coordinates'] = [POINT] + line if route.name == 'CBD to Kamangu' else line + [POINT]
        route.geometry = geometry
        route.save(update_fields=['geometry'])


class Migration(migrations.Migration):
    dependencies = [('companies', '0022_city_shuttle_archives_terminus')]

    operations = [migrations.RunPython(extend, migrations.RunPython.noop)]
