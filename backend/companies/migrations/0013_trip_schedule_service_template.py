from django.db import migrations, models


def preserve_existing_recurring_schedules(apps, schema_editor):
    schedule = apps.get_model('companies', 'TripSchedule')
    schedule.objects.all().update(auto_renew=True)


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0012_trip_schedule'),
    ]

    operations = [
        migrations.AddField(
            model_name='tripschedule',
            name='service_end_time',
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tripschedule',
            name='normal_interval_minutes',
            field=models.PositiveSmallIntegerField(default=60),
        ),
        migrations.AddField(
            model_name='tripschedule',
            name='rush_interval_minutes',
            field=models.PositiveSmallIntegerField(default=30),
        ),
        migrations.AddField(
            model_name='tripschedule',
            name='rush_start_time',
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tripschedule',
            name='rush_end_time',
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tripschedule',
            name='auto_renew',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            preserve_existing_recurring_schedules,
            migrations.RunPython.noop,
        ),
    ]
