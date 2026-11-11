from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from buses.models import Bus
from companies.models import Company

User = get_user_model()


class PlatelessBusProbe(APITestCase):
    def setUp(self):
        self.co = Company.objects.create(name='Metro')
        self.mgr = User.objects.create_user(
            username='m', password='x', phone_number='+254700000901',
            company=self.co, role='company_manager')
        self.client.force_authenticate(self.mgr)
        self.a = Bus.objects.create(company=self.co, bus_number='SM-1', registration_number=None,
                                    vehicle_type='bus_51', capacity=51)
        self.b = Bus.objects.create(company=self.co, bus_number='SM-2', registration_number=None,
                                    vehicle_type='bus_51', capacity=51)

    def test_two_plateless_buses_coexist(self):
        self.assertEqual(Bus.objects.filter(registration_number__isnull=True).count(), 2)

    def test_str_and_list(self):
        self.assertIn('no plate', str(self.a))
        r = self.client.get(f'/api/buses/?company_id={self.co.id}')
        self.assertEqual(r.status_code, 200, r.content)

    def test_patch_adds_plate_later(self):
        r = self.client.patch(f'/api/buses/{self.a.id}/', {'registration_number': 'kda 551a'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['registration_number'], 'KDA 551A')

    def test_patch_other_field_keeps_null(self):
        r = self.client.patch(f'/api/buses/{self.a.id}/', {'maintenance_status': 'maintenance'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.a.refresh_from_db()
        self.assertIsNone(self.a.registration_number)

    def test_patch_null_or_blank_plate_refused(self):
        self.a.registration_number = 'KDA 551A'
        self.a.save()
        for v in (None, '', '   '):
            r = self.client.patch(f'/api/buses/{self.a.id}/', {'registration_number': v}, format='json')
            self.assertEqual(r.status_code, 400, (v, r.content))
        self.a.refresh_from_db()
        self.assertEqual(self.a.registration_number, 'KDA 551A')

    def test_duplicate_plate_refused(self):
        self.a.registration_number = 'KDA 551A'
        self.a.save()
        r = self.client.patch(f'/api/buses/{self.b.id}/', {'registration_number': 'KDA 551A'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_put_without_plate_on_plateless_bus(self):
        r = self.client.put(f'/api/buses/{self.a.id}/', {'bus_number': 'SM-1', 'vehicle_type': 'bus_51'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
