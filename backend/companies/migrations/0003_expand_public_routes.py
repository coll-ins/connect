from django.db import migrations


# Public route listings checked on 2026-09-14. Fares are provisional estimates
# because the published sources list destinations but not a complete fare table.
ROUTES = {
    'Supermetro': [
        ('CBD to Kikuyu', 'Nairobi CBD', 'Kikuyu', '80.00'),
        ('CBD to Juja', 'Nairobi CBD', 'Juja', '80.00'),
        ('CBD to Makongeni', 'Nairobi CBD', 'Makongeni', '80.00'),
        ('CBD to Thika Town', 'Nairobi CBD', 'Thika Town', '100.00'),
        ('CBD to Kitengela', 'Nairobi CBD', 'Kitengela', '100.00'),
        ('Nairobi to Kisumu', 'Nairobi', 'Kisumu', '1000.00'),
        ('Nairobi to Kakamega', 'Nairobi', 'Kakamega', '1200.00'),
        ('CBD to JKIA', 'Nairobi CBD', 'JKIA', '100.00'),
        ('CBD to Mlolongo', 'Nairobi CBD', 'Mlolongo', '80.00'),
        ('CBD to Cabanas', 'Nairobi CBD', 'Cabanas', '80.00'),
        ('CBD to Taj Mall', 'Nairobi CBD', 'Taj Mall', '80.00'),
        ('CBD to Pipeline', 'Nairobi CBD', 'Pipeline', '80.00'),
        ('CBD to Jogoo Road', 'Nairobi CBD', 'Jogoo Road', '60.00'),
        ('CBD to Mfangano', 'Nairobi CBD', 'Mfangano', '60.00'),
    ],
    'CityShuttle': [
        ('CBD to Upper Hill', 'Nairobi CBD', 'Upper Hill', '70.00'),
        ('CBD to Ngong Road', 'Nairobi CBD', 'Ngong Road', '70.00'),
    ],
    'Latema': [
        ('CBD to Waiyaki Way', 'Nairobi CBD', 'Waiyaki Way', '70.00'),
        ('CBD to Kikuyu', 'Nairobi CBD', 'Kikuyu', '80.00'),
        ('CBD to Kinoo', 'Nairobi CBD', 'Kinoo', '80.00'),
        ('CBD to Uthiru', 'Nairobi CBD', 'Uthiru', '70.00'),
        ('CBD to Kawangware', 'Nairobi CBD', 'Kawangware', '70.00'),
        ('CBD to Kabiria', 'Nairobi CBD', 'Kabiria / Satellite', '80.00'),
        ('CBD to Ngong Road', 'Nairobi CBD', 'Ngong Road', '70.00'),
        ('CBD to Adams Arcade', 'Nairobi CBD', 'Adams Arcade', '70.00'),
        ('CBD to Gachie', 'Nairobi CBD', 'Gachie', '100.00'),
        ('CBD to Thika Road', 'Nairobi CBD', 'Thika Road', '80.00'),
        ('CBD to Juja', 'Nairobi CBD', 'Juja', '80.00'),
        ('CBD to Makongeni', 'Nairobi CBD', 'Makongeni', '80.00'),
        ('Nairobi to Nakuru', 'Nairobi', 'Nakuru', '500.00'),
    ],
}


def add_routes(apps, schema_editor):
    Company = apps.get_model('companies', 'Company')
    Route = apps.get_model('companies', 'Route')

    for company_name, routes in ROUTES.items():
        company = Company.objects.get(name=company_name)
        for name, start_point, end_point, price in routes:
            Route.objects.get_or_create(
                company=company,
                name=name,
                defaults={
                    'start_point': start_point,
                    'end_point': end_point,
                    'price': price,
                },
            )


def remove_routes(apps, schema_editor):
    Company = apps.get_model('companies', 'Company')
    Route = apps.get_model('companies', 'Route')
    route_names = [route[0] for routes in ROUTES.values() for route in routes]
    Route.objects.filter(company__name__in=ROUTES, name__in=route_names).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('companies', '0002_seed_companies'),
    ]

    operations = [migrations.RunPython(add_routes, remove_routes)]