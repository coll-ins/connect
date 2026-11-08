COMPANY_ROLES = {
    'company_manager',
    'company_auditor',
    'company_operator',
}


def can_manage_company(user, company=None):
    """
    Check whether a user can manage a company.

    Superusers can manage any company.
    Company managers can manage only their assigned company.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    if user.role != 'company_manager':
        return False

    if user.company_id is None:
        return False

    if company is not None:
        company_id = getattr(company, 'id', company)
        return user.company_id == company_id

    return True


def can_access_company(user, company_id):
    """
    Check whether a user can access a specific company.

    Superusers can access every company.
    Company staff can access only their own company.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    if user.role not in COMPANY_ROLES:
        return False

    return user.company_id == company_id
