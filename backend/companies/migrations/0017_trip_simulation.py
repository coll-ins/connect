from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('companies', '0016_demo_trip_simulation'),
    ]

    operations = [
        migrations.DeleteModel(name='DemoTripSimulation'),
        migrations.CreateModel(
            name='TripSimulation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('path', models.JSONField()),
                ('position_index', models.PositiveSmallIntegerField(default=0)),
                ('status', models.CharField(choices=[('running', 'Running'), ('stopped', 'Stopped'), ('completed', 'Completed'), ('expired', 'Expired')], default='running', max_length=10)),
                ('expires_at', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('started_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='trip_simulations', to=settings.AUTH_USER_MODEL)),
                ('trip', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='simulations', to='companies.trip')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='tripsimulation',
            constraint=models.UniqueConstraint(condition=Q(('status', 'running')), fields=('status',), name='uniq_running_trip_simulation'),
        ),
    ]
