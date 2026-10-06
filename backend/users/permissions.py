from rest_framework.permissions import BasePermission


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


class IsCompanyManager(BasePermission):
    """
    Allows only a company manager or Django superuser.
    """

    def has_permission(self, request, view):
        return can_manage_company(request.user)


class IsCompanyAuditor(BasePermission):
    """
    Allows only a company auditor or Django superuser.
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        return (
            user.role == 'company_auditor'
            and user.company_id is not None
        )


class IsCompanyOperator(BasePermission):
    """
    Allows only a company operator or Django superuser.
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        return (
            user.role == 'company_operator'
            and user.company_id is not None
        )


class IsCompanyStaff(BasePermission):
    """
    Allows any company Manager, Auditor, or Operator.
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        return (
            user.role in COMPANY_ROLES
            and user.company_id is not None
        )
