from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('bookings', '0002_initial')]

    operations = [migrations.AddField(
        model_name='booking',
        name='seats',
        field=models.PositiveIntegerField(default=1),
    )]