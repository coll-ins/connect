import {
  Activity,
  BarChart3,
  Bus,
  CalendarDays,
  CarFront,
  ClipboardList,
  CreditCard,
  Gauge,
  MapPin,
  Route,
  Settings,
  ShieldCheck,
  UserRound,
  Users,
  WalletCards,
} from 'lucide-react';

export const navigationByRole = {
  passenger: [
    { label: 'Overview', icon: Gauge, path: '/passenger' },
    { label: 'Schedules', icon: CalendarDays, path: '/passenger/schedules' },
    { label: 'Live Map', icon: MapPin, path: '/passenger/map' },
    { label: 'Seats', icon: Bus, path: '/passenger/seats' },
    { label: 'Bookings', icon: ClipboardList, path: '/passenger/bookings' },
    { label: 'Wallet', icon: WalletCards, path: '/passenger/wallet' },
    { label: 'Payments', icon: CreditCard, path: '/passenger/payments' },
    { label: 'Receipts', icon: WalletCards, path: '/passenger/receipts' },
    { label: 'Activity / History', icon: Activity, path: '/passenger/history' },
    { label: 'Help & Issues', icon: ShieldCheck, path: '/passenger/help' },
    { label: 'Profile', icon: UserRound, path: '/passenger/profile' },
  ],

  driver: [
    { label: 'Overview', icon: Gauge, path: '/driver' },
    { label: "Today's Trips", icon: CalendarDays, path: '/driver/trips' },
    { label: 'Passengers', icon: Users, path: '/driver/passengers' },
    { label: 'Live Location', icon: MapPin, path: '/driver/location' },
    { label: 'Boarding', icon: ShieldCheck, path: '/driver/boarding' },
    { label: 'Profile', icon: UserRound, path: '/driver/profile' },
  ],

  company_manager: [
    { label: 'Overview', icon: Gauge, path: '/company-manager' },
    { label: 'Trips', icon: CalendarDays, path: '/company-manager/trips' },
    { label: 'Bookings', icon: ClipboardList, path: '/company-manager/bookings' },
    { label: 'Drivers', icon: Users, path: '/company-manager/drivers' },
    { label: 'Routes', icon: Route, path: '/company-manager/routes' },
    { label: 'Revenue', icon: BarChart3, path: '/company-manager/revenue' },
    { label: 'Settings', icon: Settings, path: '/company-manager/settings' },
  ],

  company_auditor: [
    { label: 'Overview', icon: Gauge, path: '/company-auditor' },
    { label: 'Trips', icon: CalendarDays, path: '/company-auditor/trips' },
    { label: 'Bookings', icon: ClipboardList, path: '/company-auditor/bookings' },
    { label: 'Revenue', icon: BarChart3, path: '/company-auditor/revenue' },
    { label: 'Audit', icon: ShieldCheck, path: '/company-auditor/audit' },
  ],

  company_operator: [
    { label: 'Operations', icon: Activity, path: '/company-operator' },
    { label: "Today's Trips", icon: CalendarDays, path: '/company-operator/trips' },
    { label: 'Bookings', icon: ClipboardList, path: '/company-operator/bookings' },
    { label: 'Drivers', icon: Users, path: '/company-operator/drivers' },
    { label: 'Boarding', icon: ShieldCheck, path: '/company-operator/boarding' },
  ],

  platform_admin: [
    { label: 'Overview', icon: Gauge, path: '/platform-admin' },
    { label: 'Companies', icon: CarFront, path: '/platform-admin/companies' },
    { label: 'Drivers', icon: Users, path: '/platform-admin/drivers' },
    { label: 'Trips', icon: CalendarDays, path: '/platform-admin/trips' },
    { label: 'Bookings', icon: ClipboardList, path: '/platform-admin/bookings' },
    { label: 'Users', icon: UserRound, path: '/platform-admin/users' },
    { label: 'Reports', icon: BarChart3, path: '/platform-admin/reports' },
    { label: 'Platform', icon: Settings, path: '/platform-admin/settings' },
  ],
};

export function getNavigation(role) {
  return navigationByRole[role] || [];
}
