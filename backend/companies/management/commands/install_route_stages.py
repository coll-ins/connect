import time
from decimal import Decimal

import requests
from django.core.management.base import BaseCommand

from companies.models import Route, PickupStage


STAGES = {
    "CBD to Ngong": [
        "Kencom House",
        "Nyayo Stadium",
        "Prestige / Adams Arcade",
        "Karen / Dagoretti Corner",
        "Kiserian Junction",
        "Ngong Town",
    ],

    "CBD to Westlands": [
        "Kencom House",
        "University Way / KICC",
        "Museum Hill",
        "Westlands",
        "Sarit Centre",
    ],

    "CBD to Karen": [
        "Kencom House",
        "Kenyatta Avenue",
        "Uhuru Highway / Haile Selassie",
        "Nyayo Stadium",
        "T-Mall / Langata Road",
        "Bomas of Kenya",
        "The Hub Karen",
        "Karen Shopping Centre",
    ],

    "CBD to Eastleigh": [
        "Tom Mboya Street",
        "Globe Cinema Roundabout",
        "Pangani",
        "California / Eastleigh",
        "Eastleigh Section III",
    ],

    "CBD to Umoja": [
        "Tom Mboya Street",
        "Muthurwa",
        "Jogoo Road",
        "Donholm",
        "Umoja Innercore",
    ],

    "CBD to Kikuyu": [
        "Kencom House",
        "University Way",
        "Museum Hill",
        "Westlands",
        "Kangemi",
        "Mountain View",
        "Uthiru",
        "Kinoo",
        "Kikuyu",
    ],

    "CBD to Juja": [
        "Tom Mboya Street",
        "Pangani",
        "Thika Road Mall",
        "Ruiru Town",
        "Juja Town",
    ],

    "CBD to Makongeni": [
        "Tom Mboya Street",
        "Muthurwa",
        "Jogoo Road",
        "Makadara",
        "Makongeni",
    ],

    "CBD to Thika Town": [
        "Tom Mboya Street",
        "Pangani",
        "TRM / GSU",
        "Ruiru",
        "Juja",
        "Thika Town",
    ],

    "CBD to Kitengela": [
        "Railways",
        "Nyayo Stadium",
        "Bellevue",
        "Cabanas",
        "Mlolongo",
        "Kitengela Town",
    ],

    "CBD to JKIA": [
        "Railways",
        "Nyayo Stadium",
        "South B",
        "Bellevue",
        "Cabanas",
        "JKIA",
    ],

    "CBD to Mlolongo": [
        "Railways",
        "Nyayo Stadium",
        "South B",
        "Bellevue",
        "Cabanas",
        "Mlolongo",
    ],

    "CBD to Cabanas": [
        "Railways",
        "Nyayo Stadium",
        "South B",
        "Bellevue",
        "Cabanas",
    ],

    "CBD to Taj Mall": [
        "Railways",
        "Nyayo Stadium",
        "South B",
        "Bellevue",
        "Cabanas",
        "Taj Mall",
    ],

    "CBD to Pipeline": [
        "Tom Mboya Street",
        "Muthurwa",
        "Jogoo Road",
        "Donholm",
        "Outer Ring Road",
        "Pipeline",
    ],

    "CBD to Jogoo Road": [
        "Tom Mboya Street",
        "Muthurwa",
        "Jogoo Road",
        "Makadara",
        "Buruburu",
    ],

    "CBD to Mfangano": [
        "Kencom House",
        "Moi Avenue",
        "Mfangano Street",
    ],

    "CBD to Upper Hill": [
        "Kencom House",
        "Kenyatta Avenue",
        "Community",
        "Upper Hill",
        "Kenya National Hospital",
    ],

    "CBD to Ngong Road": [
        "Kencom House",
        "Kenyatta Avenue",
        "Nyayo Stadium",
        "Prestige",
        "Adams Arcade",
        "Junction Mall",
        "Ngong Road",
    ],

    "CBD to Waiyaki Way": [
        "Kencom House",
        "University Way",
        "Museum Hill",
        "Chiromo",
        "Westlands",
        "Waiyaki Way",
    ],

    "CBD to Kinoo": [
        "Kencom House",
        "University Way",
        "Museum Hill",
        "Westlands",
        "Kangemi",
        "Kinoo",
    ],

    "CBD to Uthiru": [
        "Kencom House",
        "University Way",
        "Museum Hill",
        "Westlands",
        "Kangemi",
        "Uthiru",
    ],

    "CBD to Kawangware": [
        "Kencom House",
        "Museum Hill",
        "Westlands",
        "Kangemi",
        "Kawangware 46",
    ],

    "CBD to Kabiria": [
        "Kencom House",
        "Kenyatta Avenue",
        "Nyayo Stadium",
        "Prestige",
        "Adams Arcade",
        "Dagoretti Corner",
        "Naivasha Road",
        "Kabiria",
    ],

    "CBD to Adams Arcade": [
        "Kencom House",
        "Kenyatta Avenue",
        "Nyayo Stadium",
        "Prestige",
        "Adams Arcade",
    ],

    "CBD to Gachie": [
        "Kencom House",
        "University Way",
        "Museum Hill",
        "Westlands",
        "Parklands",
        "Gigiri",
        "Gachie",
    ],

    "CBD to Thika Road": [
        "Tom Mboya Street",
        "Pangani",
        "Muthaiga",
        "Roysambu",
        "TRM",
        "Kasarani",
        "Githurai",
        "Ruiru",
    ],

    "CBD to Nakuru": [
        "Railways",
        "Westlands",
        "Kangemi",
        "Limuru",
        "Naivasha",
        "Gilgil",
        "Nakuru",
    ],

    "CBD to Kisumu": [
        "Railways",
        "Westlands",
        "Limuru",
        "Naivasha",
        "Gilgil",
        "Nakuru",
        "Kericho",
        "Kisumu",
    ],

    "CBD to Kakamega": [
        "Railways",
        "Westlands",
        "Limuru",
        "Naivasha",
        "Nakuru",
        "Kapsabet",
        "Kakamega",
    ],

    "Kamau": [
        "CBD",
        "Muthaiga",
        "Roysambu",
        "Kasarani",
        "Ruiru",
    ],
}


class Command(BaseCommand):
    help = "Install curated pickup stages using geocoded locations."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache = {}

    def geocode(self, name):
        if name in self.cache:
            return self.cache[name]

        url = "https://photon.komoot.io/api/"

        try:
            response = requests.get(
                url,
                params={
                    "q": f"{name}, Nairobi, Kenya",
                    "limit": 1,
                },
                headers={
                    "User-Agent": "ConnectMatatuBooking/1.0",
                },
                timeout=20,
            )

            response.raise_for_status()
            data = response.json()

            features = data.get("features", [])

            if not features:
                self.stdout.write(
                    self.style.WARNING(
                        f"  unresolved: {name}"
                    )
                )
                self.cache[name] = None
                return None

            coordinates = features[0]["geometry"]["coordinates"]

            longitude = Decimal(str(coordinates[0]))
            latitude = Decimal(str(coordinates[1]))

            self.cache[name] = (latitude, longitude)

            # Small delay so the public service is not hammered.
            time.sleep(0.4)

            return self.cache[name]

        except (requests.RequestException, KeyError, ValueError) as exc:
            self.stdout.write(
                self.style.WARNING(
                    f"  geocoder error for {name}: {exc}"
                )
            )
            self.cache[name] = None
            return None

    def handle(self, *args, **options):
        created = 0
        existing = 0
        unresolved = 0

        for route_name, stage_names in STAGES.items():
            routes = Route.objects.filter(name=route_name)

            if not routes.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"Route not found: {route_name}"
                    )
                )
                continue

            for route in routes:
                self.stdout.write(
                    f"\n{route.name} ({route.company.name})"
                )

                for order, stage_name in enumerate(
                    stage_names,
                    start=1,
                ):
                    coordinates = self.geocode(stage_name)

                    if not coordinates:
                        unresolved += 1
                        continue

                    latitude, longitude = coordinates

                    stage, was_created = PickupStage.objects.get_or_create(
                        route=route,
                        name=stage_name,
                        defaults={
                            "latitude": latitude,
                            "longitude": longitude,
                            "order": order,
                            "is_active": True,
                            "source": "manual",
                        },
                    )

                    if was_created:
                        created += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  + {order}. {stage_name}"
                            )
                        )
                    else:
                        existing += 1
                        self.stdout.write(
                            f"  = {order}. {stage_name}"
                        )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Created={created} "
                f"Existing={existing} "
                f"Unresolved={unresolved}"
            )
        )
