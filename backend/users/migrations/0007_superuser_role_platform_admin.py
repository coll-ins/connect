from django.db import migrations


def sync_roles(apps, schema_editor):
    User = apps.get_model('users', 'CustomUser')
    User.objects.filter(is_superuser=True).exclude(
        role='platform_admin').update(role='platform_admin')


class Migration(migrations.Migration):
    dependencies = [('users', '0006_operator_route_scope')]
    operations = [migrations.RunPython(sync_roles, migrations.RunPython.noop)]
