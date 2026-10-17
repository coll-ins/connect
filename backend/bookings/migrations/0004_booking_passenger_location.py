from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('bookings', '0003_booking_seats'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='passenger_latitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='passenger_longitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
    ]