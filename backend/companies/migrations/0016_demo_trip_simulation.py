from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('companies', '0015_weekly_operations_report'),
    ]

    operations = [
        migrations.CreateModel(
            name='DemoTripSimulation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('route_id', models.PositiveBigIntegerField()),
                ('route_name', models.CharField(max_length=200)),
                ('company_name', models.CharField(max_length=100)),
                ('start_point', models.CharField(max_length=100)),
                ('end_point', models.CharField(max_length=100)),
                ('bus_number', models.CharField(default='DEMO BUS', max_length=30)),
                ('path', models.JSONField()),
                ('position_index', models.PositiveSmallIntegerField(default=0)),
                ('status', models.CharField(choices=[('running', 'Running'), ('completed', 'Completed'), ('stopped', 'Stopped'), ('expired', 'Expired')], default='running', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('expires_at', models.DateTimeField()),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='demo_trip_simulations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='demotripsimulation',
            constraint=models.UniqueConstraint(condition=Q(('status', 'running')), fields=('status',), name='uniq_running_demo_trip_simulation'),
        ),
    ]
