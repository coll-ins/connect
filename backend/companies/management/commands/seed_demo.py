"""DEV ONLY: repeatable demo data. Refuses to run when DEBUG is off."""
import datetime as dt

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from companies.models import Route, Trip
from drivers.models import Driver

PASSWORD = 'demo-pass-123'


class Command(BaseCommand):
    help = 'Create a boarding trip + a scheduled trip and demo logins (DEV only).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--drive', action='store_true',
            help='Send two GPS fixes away from the stage as the demo driver.',
        )

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError('seed_demo only runs with DEBUG=True.')
        User = get_user_model()

        route = (
            Route.objects.filter(pickup_stages__is_active=True)
            .distinct().order_by('id').first()
        )
        if route is None:
            raise CommandError('No route with an active pickup stage exists.')
        company = route.company
        stage = route.pickup_stages.filter(is_active=True).order_by('order', 'id').first()

        def driver_for(bus, phone, name):
            d, _ = Driver.objects.get_or_create(
                company=company, bus_number=bus,
                defaults={'name': name, 'phone_number': phone},
            )
            d.is_available = True
            d.latitude, d.longitude = float(stage.latitude), float(stage.longitude)
            d.save()
            return d

        d1 = driver_for('DEMO-001', '+254799000010', 'Demo Driver')
        d2 = driver_for('DEMO-002', '+254799000011', 'Demo Driver 2')

        if opts['drive']:
            return self._drive(d1, stage)

        Trip.objects.filter(driver__in=[d1, d2]).delete()
        boarding = Trip.objects.create(
            route=route, driver=d1, capacity=14, status='boarding',
            departure_at=timezone.now() - dt.timedelta(minutes=3))
        later = Trip.objects.create(
            route=route, driver=d2, capacity=14, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=3))

        def account(username, phone, role, with_company):
            u, _ = User.objects.get_or_create(
                username=username,
                defaults={'phone_number': phone, 'role': role},
            )
            u.role = role
            u.company = company if with_company else None
            u.set_password(PASSWORD)
            u.save()
            return u

        account('demo_passenger', '+254799000001', 'passenger', False)
        account('demo_operator', '+254799000002', 'company_operator', True)
        account('demo_driver', d1.phone_number, 'driver', True)

        self.stdout.write(self.style.SUCCESS(
            f'Route: {route.name} ({company.name}) | first stage: {stage.name}\n'
            f'Boarding trip id {boarding.id} (bus DEMO-001) | scheduled trip id {later.id}\n'
            f'Logins (password {PASSWORD}): demo_passenger, demo_operator, demo_driver\n'
            f'Then run:  python manage.py seed_demo --drive'))

    def _drive(self, driver, stage):
        User = get_user_model()
        user = User.objects.filter(username='demo_driver').first()
        if user is None:
            raise CommandError('Run seed_demo once without --drive first.')
        client = APIClient()
        client.force_authenticate(user=user)
        url = reverse('drivers:driver-location', kwargs={'driver_id': driver.id})
        lat, lng = float(stage.latitude), float(stage.longitude)
        for step, delta in enumerate((0.004, 0.006), start=1):
            resp = client.post(url, {'latitude': lat, 'longitude': lng + delta}, format='json')
            trip = Trip.objects.filter(driver=driver).order_by('-id').first()
            self.stdout.write(f'fix {step}: HTTP {resp.status_code}, trip is now {trip.status}')
