"""Route specialization for company operators."""


def operator_route_ids(user):
    """None means unrestricted; otherwise the set of route ids this operator handles."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    if user.is_superuser or getattr(user, "role", None) != "company_operator":
        return None
    if getattr(user, "all_routes", True):
        return None
    return set(user.assigned_routes.values_list("id", flat=True))


def can_handle_route(user, route_id):
    ids = operator_route_ids(user)
    return ids is None or route_id in ids
