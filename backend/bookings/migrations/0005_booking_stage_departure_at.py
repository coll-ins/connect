from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('bookings', '0004_booking_passenger_location'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='stage_departure_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]