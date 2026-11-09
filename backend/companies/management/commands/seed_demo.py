"""DEV ONLY: repeatable demo data. Refuses to run when DEBUG is off."""
import datetime as dt

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from buses.models import Bus
from companies.models import PickupStage, Route, Trip
from drivers.models import Driver

import os

PASSWORD = os.environ.get('DEMO_PASSWORD', 'demo-pass-123')


class Command(BaseCommand):
    help = 'Create a boarding trip, a scheduled trip and sample logins (DEV only).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--drive', action='store_true',
            help='Send two GPS fixes away from the stage as the seeded driver.',
        )

    def handle(self, *args, **opts):
        # Not staging either: it creates a superuser with a known password.
        if not settings.DEBUG or settings.APP_ENVIRONMENT not in ('development', 'test'):
            raise CommandError(
                'seed_demo is limited to development/test DEBUG environments.'
            )
        User = get_user_model()

        route = (
            Route.objects.filter(pickup_stages__is_active=True)
            .distinct().order_by('id').first()
        )
        if route is None:
            # Fresh database: the seeded routes have no stages yet.
            route = Route.objects.order_by('id').first()
            if route is None:
                raise CommandError('No route exists.')
            PickupStage.objects.create(
                route=route, name='Kencom House', order=1,
                latitude='-1.285582', longitude='36.824962')
            # A second stage gives the route a drawable path.
            PickupStage.objects.create(
                route=route, name='Prestige', order=2,
                latitude='-1.299720', longitude='36.787239')
        company = route.company
        stage = route.pickup_stages.filter(is_active=True).order_by('order', 'id').first()

        def driver_for(bus, phone, name):
            d, _ = Driver.objects.get_or_create(
                company=company, bus_number=bus,
                defaults={'name': name, 'phone_number': phone},
            )
            d.is_available = True
            d.name = name
            d.latitude, d.longitude = float(stage.latitude), float(stage.longitude)
            d.save()
            return d

        d1 = driver_for('KDA 123A', '+254799000010', 'Peter Mwangi')
        d2 = driver_for('KDB 456B', '+254799000011', 'Joseph Kiprop')

        if opts['drive']:
            return self._drive(d1, stage)

        def bus_for(plate, fleet, vehicle_type):
            b, _ = Bus.objects.get_or_create(
                registration_number=plate,
                defaults={'company': company, 'bus_number': fleet,
                          'vehicle_type': vehicle_type, 'capacity': 1},
            )
            return b

        Trip.objects.filter(driver__in=[d1, d2]).delete()
        boarding = Trip.objects.create(
            route=route, driver=d1, bus=bus_for('KDA 123A', 'D1', 'matatu_14'),
            capacity=14, status='boarding',
            departure_at=timezone.now() - dt.timedelta(minutes=3))
        later = Trip.objects.create(
            route=route, driver=d2, bus=bus_for('KDB 456B', 'D2', 'minibus_33'),
            capacity=33, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=3))

        def account(username, phone, role, with_company, first, last):
            u, _ = User.objects.get_or_create(
                username=username,
                defaults={'phone_number': phone, 'role': role},
            )
            u.first_name, u.last_name = first, last
            u.role = role
            u.company = company if with_company else None
            u.set_password(PASSWORD)
            u.save()
            return u

        rider = account('wanjiku.k', '+254799000001', 'passenger', False, 'Wanjiku', 'Kamau')
        # A regular rider, so cash on board shows wherever CASH_ENABLED is on.
        User.objects.filter(pk=rider.pk).update(
            boarded_count=30, date_joined=timezone.now() - dt.timedelta(days=90),
        )
        account('brian.o', '+254799000002', 'company_operator', True, 'Brian', 'Otieno')
        account('peter.m', d1.phone_number, 'driver', True, 'Peter', 'Mwangi')
        account('achieng.o', '+254799000003', 'company_manager', True, 'Achieng', 'Odhiambo')
        account('salim.h', '+254799000004', 'company_auditor', True, 'Salim', 'Hassan')
        admin = account('mercy.n', '+254799000005', 'platform_admin', False, 'Mercy', 'Njeri')
        admin.is_staff = admin.is_superuser = True
        admin.save(update_fields=['is_staff', 'is_superuser'])

        self.stdout.write(self.style.SUCCESS(
            f'Route: {route.name} ({company.name}) | first stage: {stage.name}\n'
            f'Boarding trip id {boarding.id} (bus KDA 123A) | scheduled trip id {later.id}\n'
            f'Logins (password {PASSWORD}): wanjiku.k (passenger), brian.o, peter.m (driver), '
            f'achieng.o, salim.h, mercy.n (platform admin)\n'
            f'Then run:  python manage.py seed_demo --drive'))

    def _drive(self, driver, stage):
        User = get_user_model()
        user = User.objects.filter(username='peter.m').first()
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
