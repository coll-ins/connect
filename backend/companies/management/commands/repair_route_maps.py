import json
import time
import urllib.parse
import urllib.request

from django.core.management.base import BaseCommand
from django.db import transaction

from companies.models import Route, PickupStage


OSRM_URL = "https://router.project-osrm.org/route/v1/driving"

# Coordinates verified against geographic/OSM sources.
FIXES = {
    "Kikuyu": (-1.24630, 36.66290),
    "Kitengela Town": (-1.48011, 36.96050),
    "Juja Town": (-1.10149, 37.01595),
    "Juja": (-1.10149, 37.01595),
    "Ruiru Town": (-1.14730, 36.96040),
    "Ruiru": (-1.14730, 36.96040),
    "Ngong Town": (-1.352697, 36.669901),
    "Naivasha Road": (-1.29807, 36.75798),
}


def osrm_route(points):
    """
    points = [(lat, lon), ...]
    Returns a full GeoJSON LineString following roads.
    """
    coords = ";".join(
        f"{lon},{lat}"
        for lat, lon in points
    )

    url = (
        f"{OSRM_URL}/{coords}"
        "?overview=full"
        "&geometries=geojson"
        "&steps=false"
        "&continue_straight=true"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ConnectMatatuBooking/1.0"
        },
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))

    if data.get("code") != "Ok":
        raise RuntimeError(
            f"OSRM returned {data.get('code')}: {data}"
        )

    geometry = data["routes"][0]["geometry"]

    if geometry.get("type") != "LineString":
        raise RuntimeError("OSRM did not return a LineString.")

    if len(geometry.get("coordinates", [])) < 2:
        raise RuntimeError("OSRM returned too few geometry points.")

    return geometry


class Command(BaseCommand):
    help = "Repair known bad pickup coordinates and generate road-following route geometry."

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.WARNING(
                "Repairing pickup coordinates and route geometry..."
            )
        )

        # ------------------------------------------------------------
        # 1. Correct known bad coordinates.
        # ------------------------------------------------------------
        changed = 0

        for stage in PickupStage.objects.all():
            fix = FIXES.get(stage.name.strip())

            if not fix:
                continue

            lat, lon = fix

            if (
                round(float(stage.latitude), 6) != round(lat, 6)
                or round(float(stage.longitude), 6) != round(lon, 6)
            ):
                stage.latitude = lat
                stage.longitude = lon
                stage.save(
                    update_fields=["latitude", "longitude"]
                )
                changed += 1

                self.stdout.write(
                    f"FIXED STAGE {stage.id}: "
                    f"{stage.name} -> {lat},{lon}"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Corrected {changed} stage coordinates."
            )
        )

        # ------------------------------------------------------------
        # 2. Split the two genuinely separate Ngong stops.
        # ------------------------------------------------------------
        route2 = Route.objects.filter(
            name="CBD to Ngong"
        ).first()

        if route2:
            combined = PickupStage.objects.filter(
                route=route2,
                name="Prestige / Adams Arcade",
                source="manual",
            ).first()

            if combined:
                # Adams Arcade is encountered before Prestige
                # when travelling from CBD toward Ngong.
                combined.name = "Adams Arcade"
                combined.latitude = -1.30073
                combined.longitude = 36.78052
                combined.order = 3
                combined.save(
                    update_fields=[
                        "name",
                        "latitude",
                        "longitude",
                        "order",
                    ]
                )

                PickupStage.objects.create(
                    route=route2,
                    name="Prestige",
                    latitude=-1.29973,
                    longitude=36.78724,
                    order=4,
                    is_active=True,
                    source="manual",
                )

                for index, stage in enumerate(
                    route2.pickup_stages.filter(
                        is_active=True
                    ).order_by("order", "id"),
                    start=1,
                ):
                    stage.order = index
                    stage.save(update_fields=["order"])

                self.stdout.write(
                    self.style.SUCCESS(
                        "Split CBD to Ngong: "
                        "Prestige / Adams Arcade -> "
                        "Adams Arcade + Prestige"
                    )
                )

        # ------------------------------------------------------------
        # 3. Build road-following geometry through each route's
        #    ordered pickup stages.
        # ------------------------------------------------------------
        routes = Route.objects.all().order_by("id")

        successful = 0
        failed = 0
        skipped = 0

        for route in routes:
            stages = list(
                route.pickup_stages
                .filter(is_active=True)
                .order_by("order", "id")
            )

            if len(stages) < 2:
                skipped += 1
                self.stdout.write(
                    f"SKIP {route.id} {route.name}: "
                    f"only {len(stages)} active stage(s)"
                )
                continue

            points = [
                (
                    float(stage.latitude),
                    float(stage.longitude),
                )
                for stage in stages
            ]

            try:
                geometry = osrm_route(points)

                with transaction.atomic():
                    route.geometry = geometry
                    route.start_latitude = points[0][0]
                    route.start_longitude = points[0][1]
                    route.end_latitude = points[-1][0]
                    route.end_longitude = points[-1][1]

                    route.save(
                        update_fields=[
                            "geometry",
                            "start_latitude",
                            "start_longitude",
                            "end_latitude",
                            "end_longitude",
                        ]
                    )

                successful += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"OK ROUTE {route.id}: {route.name} "
                        f"({len(stages)} stages, "
                        f"{len(geometry['coordinates'])} road points)"
                    )
                )

            except Exception as exc:
                failed += 1

                self.stdout.write(
                    self.style.ERROR(
                        f"FAILED ROUTE {route.id}: "
                        f"{route.name}: {exc}"
                    )
                )

            # Be polite to the public routing server.
            time.sleep(0.5)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"FINISHED: success={successful}, "
                f"failed={failed}, skipped={skipped}"
            )
        )
