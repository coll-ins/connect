from django.db import transaction

from companies.models import Route, PickupStage
from .map_service import (
    geocode_place,
    build_route_geometry,
    discover_bus_stops,
    order_stages_along_route,
)


@transaction.atomic
def configure_route_map(route_id):
    route = Route.objects.select_for_update().get(id=route_id)

    # ---------------------------------------------------------
    # 1. Geocode route endpoints
    # ---------------------------------------------------------
    start_lat, start_lon = geocode_place(route.start_point)
    end_lat, end_lon = geocode_place(route.end_point)

    # ---------------------------------------------------------
    # 2. Build real road-following geometry
    # ---------------------------------------------------------
    geometry = build_route_geometry(
        start_lat,
        start_lon,
        end_lat,
        end_lon,
    )

    # ---------------------------------------------------------
    # 3. Save the route map immediately.
    #
    # Automatic OSM pickup discovery must NOT be allowed
    # to roll this back.
    # ---------------------------------------------------------
    route.start_latitude = start_lat
    route.start_longitude = start_lon
    route.end_latitude = end_lat
    route.end_longitude = end_lon
    route.geometry = geometry

    route.save(
        update_fields=[
            "start_latitude",
            "start_longitude",
            "end_latitude",
            "end_longitude",
            "geometry",
        ]
    )

    # ---------------------------------------------------------
    # 4. Automatic OSM stages are optional.
    # ---------------------------------------------------------
    automatic_stages = []

    try:
        automatic_stages = discover_bus_stops(geometry)
        automatic_stages = order_stages_along_route(
            geometry,
            automatic_stages,
        )
    except Exception as exc:
        print(
            f"Automatic pickup-stage discovery failed: {exc}"
        )

    # ---------------------------------------------------------
    # 5. Replace previous AUTOMATIC stages only when discovery
    #    actually returned usable stages.
    #
    # Manual company stages are never deleted.
    # If an external map service is unavailable, preserve the
    # existing automatic stages instead of wiping them.
    # ---------------------------------------------------------
    created_stages = []

    if not automatic_stages:
        print(
            "No automatic pickup stages discovered. "
            "Existing automatic stages were preserved."
        )
        return route, created_stages

    placeholder_names = {
        "unnamed",
        "unnamed bus stop",
        "unnamed stop",
        "unknown",
        "unknown stop",
        "bus stop",
        "stop",
    }

    valid_stages = []

    for stage in automatic_stages:
        name = " ".join(str(stage.get("name", "")).strip().split())

        # Never expose placeholder OSM names to passengers.
        if not name or name.lower() in placeholder_names:
            print(
                "Skipping unnamed automatic pickup stage at "
                f"{stage.get('latitude')}, {stage.get('longitude')}"
            )
            continue

        valid_stages.append(
            {
                **stage,
                "name": name,
            }
        )

    if not valid_stages:
        print(
            "Automatic discovery returned no usable named stages. "
            "Existing automatic stages were preserved."
        )
        return route, created_stages

    PickupStage.objects.filter(
        route=route,
        source="automatic",
    ).delete()

    for stage in valid_stages:
        created_stages.append(
            PickupStage.objects.create(
                route=route,
                name=stage["name"],
                latitude=stage["latitude"],
                longitude=stage["longitude"],
                order=stage["order"],
                is_active=True,
                source="automatic",
                source_ref=stage["source_ref"],
            )
        )

    return route, created_stages
