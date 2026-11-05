from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0013_trip_schedule_service_template'),
    ]

    operations = [
        migrations.AddField(
            model_name='tripschedule',
            name='generation_checked_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tripschedule',
            name='driver_unavailable_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='tripschedule',
            name='driver_conflict_count',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
