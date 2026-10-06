export function dashboardPath(user) {
  if (!user) return '/login';

  switch (user.role) {
    case 'platform_admin':
      return '/platform-admin';

    case 'company_admin':
      return '/company-admin';

    case 'driver':
      return '/driver';

    case 'passenger':
    default:
      return '/passenger';
  }
}
