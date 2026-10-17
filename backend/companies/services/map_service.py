import json
import math
import urllib.parse
import urllib.request


USER_AGENT = "ConnectMatatuBooking/1.0"


def http_json(url, params=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def geocode_place(place):
    data = http_json(
        "https://nominatim.openstreetmap.org/search",
        {
            "q": f"{place}, Kenya",
            "format": "json",
            "limit": 1,
        },
    )

    if not data:
        raise ValueError(f"Could not find location: {place}")

    return float(data[0]["lat"]), float(data[0]["lon"])


def build_route_geometry(start_lat, start_lon, end_lat, end_lon):
    coordinates = f"{start_lon},{start_lat};{end_lon},{end_lat}"

    data = http_json(
        f"https://router.project-osrm.org/route/v1/driving/{coordinates}",
        {
            "overview": "full",
            "geometries": "geojson",
        },
    )

    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError("OSRM could not find a driving route.")

    return data["routes"][0]["geometry"]


def _sample_geometry(geometry, max_points=12):
    coordinates = geometry.get("coordinates", [])

    if len(coordinates) <= max_points:
        return coordinates

    step = (len(coordinates) - 1) / (max_points - 1)

    sampled = []

    for index in range(max_points):
        source_index = round(index * step)
        sampled.append(coordinates[source_index])

    return sampled


def reverse_geocode_stage_name(latitude, longitude):
    """Return a useful human-readable name for an unnamed OSM stop."""
    try:
        data = http_json(
            "https://nominatim.openstreetmap.org/reverse",
            {
                "lat": latitude,
                "lon": longitude,
                "format": "json",
                "zoom": 18,
                "addressdetails": 1,
            },
        )

        address = data.get("address", {})

        road = (
            address.get("road")
            or address.get("pedestrian")
            or address.get("residential")
            or address.get("footway")
        )

        if road:
            return f"{road} Stage"

        named_area = (
            address.get("neighbourhood")
            or address.get("suburb")
            or address.get("village")
            or address.get("town")
            or address.get("city_district")
        )

        if named_area:
            return f"{named_area} Stage"

    except Exception as exc:
        print(
            "Reverse geocoding pickup stage failed "
            f"at {latitude}, {longitude}: {exc}"
        )

    return None


def find_nearby_landmark_name(latitude, longitude, radius=150):
    """
    Find a recognizable nearby landmark for an unnamed pickup stage.
    """
    query = f"""
[out:json][timeout:20];
(
  nwr(around:{radius},{latitude},{longitude})["name"];
);
out center tags;
"""

    try:
        request = urllib.request.Request(
            "https://overpass.kumi.systems/api/interpreter",
            data=query.encode("utf-8"),
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "text/plain",
                "Accept": "application/json",
            },
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(
                response.read().decode("utf-8")
            )

    except Exception as exc:
        print(
            "Nearby landmark lookup failed "
            f"at {latitude}, {longitude}: {exc}"
        )
        return None

    preferred_amenities = {
        "school",
        "hospital",
        "clinic",
        "university",
        "college",
        "marketplace",
        "bus_station",
        "station",
        "police",
        "fire_station",
        "place_of_worship",
    }

    preferred_tourism = {
        "attraction",
        "hotel",
        "museum",
    }

    preferred_highways = {
        "trunk",
        "primary",
        "secondary",
        "tertiary",
    }

    candidates = []

    for element in data.get("elements", []):
        tags = element.get("tags", {})
        name = str(tags.get("name", "")).strip()

        if not name:
            continue

        if name.lower() in {
            "unnamed",
            "unnamed road",
            "unnamed bus stop",
            "unknown",
        }:
            continue

        center = element.get("center", {})

        candidate_lat = element.get(
            "lat",
            center.get("lat"),
        )
        candidate_lon = element.get(
            "lon",
            center.get("lon"),
        )

        if candidate_lat is None or candidate_lon is None:
            continue

        distance = distance_squared(
            (latitude, longitude),
            (float(candidate_lat), float(candidate_lon)),
        )

        score = 0

        if tags.get("amenity") in preferred_amenities:
            score += 100

        if tags.get("tourism") in preferred_tourism:
            score += 90

        if tags.get("highway") in preferred_highways:
            score += 80

        if tags.get("railway") in {
            "station",
            "halt",
        }:
            score += 100

        if tags.get("shop"):
            score += 40

        if tags.get("building"):
            score += 20

        score -= distance * 1000000

        candidates.append(
            (score, distance, name)
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (-item[0], item[1])
    )

    return candidates[0][2]


def discover_bus_stops(geometry, radius=200):
    coordinates = _sample_geometry(geometry, max_points=24)

    if not coordinates:
        return []

    all_elements = []

    around_parts = []

    for lon, lat in coordinates:
        around_parts.append(
            f"node(around:{radius},{lat},{lon})[highway=bus_stop];"
        )
        around_parts.append(
            f"node(around:{radius},{lat},{lon})[public_transport=platform];"
        )

    query = f"""
[out:json][timeout:30];
(
  {''.join(around_parts)}
);
out body;
"""

    overpass_endpoints = [
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass-api.de/api/interpreter",
    ]

    for endpoint in overpass_endpoints:
        try:
            request = urllib.request.Request(
                endpoint,
                data=query.encode("utf-8"),
                headers={
                    "User-Agent": USER_AGENT,
                    "Content-Type": "text/plain",
                    "Accept": "application/json",
                },
            )

            with urllib.request.urlopen(
                request,
                timeout=60,
            ) as response:
                data = json.loads(
                    response.read().decode("utf-8")
                )

            all_elements.extend(data.get("elements", []))

            if all_elements:
                break

        except Exception as exc:
            print(
                f"Overpass endpoint failed: {endpoint} - {exc}"
            )

    stages = []

    for element in all_elements:
        latitude = element.get("lat")
        longitude = element.get("lon")

        if latitude is None or longitude is None:
            continue

        tags = element.get("tags", {})

        name = (
            tags.get("name")
            or tags.get("local_ref")
            or tags.get("ref")
            or tags.get("description")
            or tags.get("operator")
        )

        # If OSM has no useful name, look for a nearby
        # recognizable landmark first.
        if not name:
            name = find_nearby_landmark_name(
                float(latitude),
                float(longitude),
            )

        # If no landmark was found, fall back to the
        # nearby road or named area.
        if not name:
            name = reverse_geocode_stage_name(
                float(latitude),
                float(longitude),
            )

        # Never create a passenger-facing placeholder.
        if name:
            name = " ".join(str(name).strip().split())

        placeholder_names = {
            "unnamed",
            "unnamed road",
            "unnamed bus stop",
            "unnamed stop",
            "unknown",
            "unknown stop",
            "bus stop",
            "stop",
        }

        if not name or name.lower() in placeholder_names:
            print(
                "Skipping unnamed pickup stage at "
                f"{latitude}, {longitude}"
            )
            continue

        stages.append(
            {
                "name": str(name).strip(),
                "latitude": float(latitude),
                "longitude": float(longitude),
                "source": "automatic",
                "source_ref": str(element.get("id")),
            }
        )

    unique = []
    seen = set()

    for stage in stages:
        key = (
            round(stage["latitude"], 5),
            round(stage["longitude"], 5),
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(stage)

    return unique

def distance_squared(point_a, point_b):
    lat1, lon1 = point_a
    lat2, lon2 = point_b

    return (
        (lat1 - lat2) ** 2
        + (lon1 - lon2) ** 2
    )


def order_stages_along_route(geometry, stages):
    coordinates = geometry.get("coordinates", [])

    if not coordinates:
        return stages

    ordered = []

    for stage in stages:
        best_index = None
        best_distance = math.inf

        for index, coordinate in enumerate(coordinates):
            lon, lat = coordinate

            distance = distance_squared(
                (stage["latitude"], stage["longitude"]),
                (lat, lon),
            )

            if distance < best_distance:
                best_distance = distance
                best_index = index

        ordered.append(
            (
                best_index if best_index is not None else 999999,
                stage,
            )
        )

    ordered.sort(key=lambda item: item[0])

    result = []

    for order, (_, stage) in enumerate(ordered, start=1):
        stage["order"] = order
        result.append(stage)

    return result
