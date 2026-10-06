export const ALL_ROLES = [
  'platform_admin',
  'company_manager',
  'company_auditor',
  'company_operator',
  'driver',
  'passenger',
];

export function dashboardPath(user) {
  if (!user) return '/login';

  switch (user.role) {
    case 'platform_admin':
      return '/platform-admin';

    case 'company_manager':
      return '/company-manager';

    case 'company_auditor':
      return '/company-auditor';

    case 'company_operator':
      return '/company-operator';

    case 'driver':
      return '/driver';

    case 'passenger':
    default:
      return '/passenger';
  }
}
