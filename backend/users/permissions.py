def is_platform_admin(user):
    """
    Platform-wide admin — can manage any company's data. Superuser
    counts too, since that's how Django admin access already works
    and we don't want two disconnected notions of 'admin'.
    """
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role == 'platform_admin')
    )


def is_company_admin_for(user, company):
    """
    True only if this user is a company_admin AND scoped to this
    exact company — a company_admin for Supermetro must never pass
    this check for Latema's data.
    """
    if not (user and user.is_authenticated and company):
        return False
    return user.role == 'company_admin' and user.company_id == company.id


def can_manage_company(user, company):
    """The check every company-scoped write endpoint should use."""
    return is_platform_admin(user) or is_company_admin_for(user, company)