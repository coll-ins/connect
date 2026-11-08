// Who runs CONNECT and how to reach them. Set these at build time (Vercel
// environment variables) once the business is registered; the legal pages
// and Help read them from here only.
// Change with TERMS_VERSION in backend/connect/settings.py.
export const LAST_UPDATED = '8 November 2026';

const env = import.meta.env;

export const BUSINESS = {
  // Registered name of the business that operates CONNECT.
  entity: env.VITE_LEGAL_ENTITY || 'CONNECT',
  email: env.VITE_SUPPORT_EMAIL || '',
  phone: env.VITE_SUPPORT_PHONE || '',
  address: env.VITE_LEGAL_ADDRESS || 'Nairobi, Kenya',
};
