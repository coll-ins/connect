from django.db import migrations


COMPANIES = [
    {
        'name': 'Supermetro',
        'description': 'Reliable city transport for everyday commuters.',
        'areas_served': 'Nairobi, CBD, Rongai, Ngong, Kiserian',
        'phone_number': '+254700000001',
        'routes': [
            ('CBD to Rongai', 'Nairobi CBD', 'Rongai', '80.00'),
            ('CBD to Ngong', 'Nairobi CBD', 'Ngong', '100.00'),
        ],
    },
    {
        'name': 'CityShuttle',
        'description': 'Convenient shuttle routes across Nairobi.',
        'areas_served': 'Nairobi, CBD, Westlands, Kilimani, Karen',
        'phone_number': '+254700000002',
        'routes': [
            ('CBD to Westlands', 'Nairobi CBD', 'Westlands', '70.00'),
            ('CBD to Karen', 'Nairobi CBD', 'Karen', '100.00'),
        ],
    },
    {
        'name': 'Latema',
        'description': 'Affordable routes connecting Nairobi neighbourhoods.',
        'areas_served': 'Nairobi, CBD, Eastleigh, Kayole, Umoja',
        'phone_number': '+254700000003',
        'routes': [
            ('CBD to Eastleigh', 'Nairobi CBD', 'Eastleigh', '60.00'),
            ('CBD to Umoja', 'Nairobi CBD', 'Umoja', '80.00'),
        ],
    },
]


def seed_companies(apps, schema_editor):
    Company = apps.get_model('companies', 'Company')
    Route = apps.get_model('companies', 'Route')

    for company_data in COMPANIES:
        routes = company_data['routes']
        company_defaults = {
            key: value for key, value in company_data.items() if key != 'routes'
        }
        company, _ = Company.objects.update_or_create(
            name=company_data['name'],
            defaults=company_defaults,
        )
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


def remove_companies(apps, schema_editor):
    Company = apps.get_model('companies', 'Company')
    Company.objects.filter(name__in=['Supermetro', 'CityShuttle', 'Latema']).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('companies', '0001_initial'),
    ]

    operations = [migrations.RunPython(seed_companies, remove_companies)]
