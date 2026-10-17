from django.db import connection
from django.utils import timezone

from bookings.models import Booking
from companies.models import Company, Route, Trip
from drivers.models import Driver
from users.models import CustomUser


def run_system_checks():
    checks = []

    # ---------------------------------------------------------
    # Database connectivity
    # ---------------------------------------------------------
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

        checks.append({
            "name": "Database connectivity",
            "status": "passed",
            "message": "Database connection is healthy.",
        })
    except Exception as exc:
        checks.append({
            "name": "Database connectivity",
            "status": "failed",
            "message": f"Database connection failed: {exc}",
        })

    # ---------------------------------------------------------
    # Basic platform counts
    # ---------------------------------------------------------
    try:
        checks.append({
            "name": "Company records",
            "status": "passed",
            "message": f"{Company.objects.count()} companies found.",
        })
    except Exception as exc:
        checks.append({
            "name": "Company records",
            "status": "failed",
            "message": f"Unable to read companies: {exc}",
        })

    try:
        checks.append({
            "name": "Route records",
            "status": "passed",
            "message": f"{Route.objects.count()} routes found.",
        })
    except Exception as exc:
        checks.append({
            "name": "Route records",
            "status": "failed",
            "message": f"Unable to read routes: {exc}",
        })

    try:
        checks.append({
            "name": "Trip records",
            "status": "passed",
            "message": f"{Trip.objects.count()} trips found.",
        })
    except Exception as exc:
        checks.append({
            "name": "Trip records",
            "status": "failed",
            "message": f"Unable to read trips: {exc}",
        })

    try:
        checks.append({
            "name": "Driver records",
            "status": "passed",
            "message": f"{Driver.objects.count()} drivers found.",
        })
    except Exception as exc:
        checks.append({
            "name": "Driver records",
            "status": "failed",
            "message": f"Unable to read drivers: {exc}",
        })

    try:
        checks.append({
            "name": "Booking records",
            "status": "passed",
            "message": f"{Booking.objects.count()} bookings found.",
        })
    except Exception as exc:
        checks.append({
            "name": "Booking records",
            "status": "failed",
            "message": f"Unable to read bookings: {exc}",
        })

    # ---------------------------------------------------------
    # Company staff integrity
    # ---------------------------------------------------------
    try:
        company_staff_without_company = CustomUser.objects.filter(
            role__in=[
                "company_manager",
                "company_auditor",
                "company_operator",
            ],
            company__isnull=True,
        ).count()

        checks.append({
            "name": "Company staff assignment",
            "status": (
                "passed"
                if company_staff_without_company == 0
                else "failed"
            ),
            "message": (
                "All company staff have a company."
                if company_staff_without_company == 0
                else (
                    f"{company_staff_without_company} company staff "
                    "account(s) have no company."
                )
            ),
        })
    except Exception as exc:
        checks.append({
            "name": "Company staff assignment",
            "status": "failed",
            "message": f"Unable to check company staff: {exc}",
        })

    # ---------------------------------------------------------
    # Driver assignment integrity
    # ---------------------------------------------------------
    try:
        drivers_without_company = Driver.objects.filter(
            company__isnull=True
        ).count()

        checks.append({
            "name": "Driver company assignment",
            "status": (
                "passed"
                if drivers_without_company == 0
                else "failed"
            ),
            "message": (
                "All drivers have a company."
                if drivers_without_company == 0
                else (
                    f"{drivers_without_company} driver(s) have no company."
                )
            ),
        })
    except Exception as exc:
        checks.append({
            "name": "Driver company assignment",
            "status": "failed",
            "message": f"Unable to check driver assignments: {exc}",
        })

    # ---------------------------------------------------------
    # Trip / driver company integrity
    # ---------------------------------------------------------
    try:
        mismatches = []

        for trip in Trip.objects.select_related(
            "route__company",
            "driver__company",
        ):
            route_company_id = trip.route.company_id
            driver_company_id = trip.driver.company_id

            if route_company_id != driver_company_id:
                mismatches.append(trip.id)

        checks.append({
            "name": "Trip driver/company integrity",
            "status": "passed" if not mismatches else "failed",
            "message": (
                "All trip drivers belong to the route company."
                if not mismatches
                else (
                    f"{len(mismatches)} trip(s) have a driver/company "
                    "mismatch."
                )
            ),
            "count": len(mismatches),
            "records": mismatches[:20],
        })
    except Exception as exc:
        checks.append({
            "name": "Trip driver/company integrity",
            "status": "failed",
            "message": f"Unable to check trip company integrity: {exc}",
        })

    # ---------------------------------------------------------
    # Past scheduled trips
    # ---------------------------------------------------------
    try:
        now = timezone.now()

        past_scheduled = list(
            Trip.objects.filter(
                status="scheduled",
                departure_at__lt=now,
            ).values_list("id", flat=True)
        )

        checks.append({
            "name": "Past scheduled trips",
            "status": "passed" if not past_scheduled else "warning",
            "message": (
                "No past trips remain scheduled."
                if not past_scheduled
                else (
                    f"{len(past_scheduled)} trip(s) are past their "
                    "departure time but still marked scheduled."
                )
            ),
            "count": len(past_scheduled),
            "records": past_scheduled[:20],
        })
    except Exception as exc:
        checks.append({
            "name": "Past scheduled trips",
            "status": "failed",
            "message": f"Unable to check trip timing: {exc}",
        })

    # ---------------------------------------------------------
    # Upcoming trips without drivers
    # ---------------------------------------------------------
    try:
        now = timezone.now()

        unassigned = list(
            Trip.objects.filter(
                departure_at__gt=now,
                driver__isnull=True,
            ).exclude(
                status__in=["completed", "cancelled", "departed"]
            ).values_list("id", flat=True)
        )

        checks.append({
            "name": "Upcoming trip driver assignment",
            "status": "passed" if not unassigned else "warning",
            "message": (
                "All upcoming active trips have drivers."
                if not unassigned
                else (
                    f"{len(unassigned)} upcoming trip(s) have "
                    "no assigned driver."
                )
            ),
            "count": len(unassigned),
            "records": unassigned[:20],
        })
    except Exception as exc:
        checks.append({
            "name": "Upcoming trip driver assignment",
            "status": "failed",
            "message": f"Unable to check upcoming trips: {exc}",
        })

    # ---------------------------------------------------------
    # Trip capacity
    # ---------------------------------------------------------
    try:
        over_capacity = []

        trips = Trip.objects.all()

        for trip in trips:
            booked_seats = (
                Booking.objects.filter(
                    trip_id=trip.id
                )
                .exclude(
                    status__in=["cancelled", "completed", "no_show"]
                )
                .values_list("seats", flat=True)
            )

            total_seats = sum(int(seats or 0) for seats in booked_seats)

            if total_seats > trip.capacity:
                over_capacity.append({
                    "trip_id": trip.id,
                    "booked_seats": total_seats,
                    "capacity": trip.capacity,
                })

        checks.append({
            "name": "Trip capacity",
            "status": "passed" if not over_capacity else "failed",
            "message": (
                "No trips exceed their seat capacity."
                if not over_capacity
                else (
                    f"{len(over_capacity)} trip(s) exceed their "
                    "configured capacity."
                )
            ),
            "count": len(over_capacity),
            "records": over_capacity[:20],
        })
    except Exception as exc:
        checks.append({
            "name": "Trip capacity",
            "status": "failed",
            "message": f"Unable to check trip capacity: {exc}",
        })

    # ---------------------------------------------------------
    # Overall result
    # ---------------------------------------------------------
    failed = sum(
        1 for check in checks
        if check["status"] == "failed"
    )

    warnings = sum(
        1 for check in checks
        if check["status"] == "warning"
    )

    if failed:
        overall_status = "critical"
    elif warnings:
        overall_status = "warning"
    else:
        overall_status = "healthy"

    return {
        "status": overall_status,
        "failed": failed,
        "warnings": warnings,
        "passed": len(checks) - failed - warnings,
        "checks": checks,
    }
