import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { apiRequest } from '../api';

const AuthContext = createContext(null);

function getStoredUser() {
  try {
    return JSON.parse(localStorage.getItem('user_session') || 'null');
  } catch {
    return null;
  }
}

const KNOWN_ROLES = [
  'platform_admin',
  'company_manager',
  'company_auditor',
  'company_operator',
  'driver',
  'passenger',
];

function normalizeRole(role, isSuperuser = false) {
  if (isSuperuser) return 'platform_admin';

  const value = String(role || '')
    .trim()
    .toLowerCase()
    .replace(/-/g, '_')
    .replace(/\s+/g, '_');

  if (value === 'admin' || value === 'superadmin') return 'platform_admin';
  if (value === 'companymanager') return 'company_manager';
  if (value === 'companyauditor') return 'company_auditor';
  if (value === 'companyoperator') return 'company_operator';

  if (KNOWN_ROLES.includes(value)) return value;

  throw new Error(
    `CONNECT received an unrecognized account role: ${String(role || '(empty)')}`
  );
}

class InvalidAccountRoleError extends Error {
  constructor(role, cause) {
    super(
      `CONNECT received an unrecognized account role: ${String(role || '(empty)')}`,
      { cause },
    );
    this.name = 'InvalidAccountRoleError';
  }
}

function normalizeUser(data) {
  const u = data?.user || data || {};

  let role;
  try {
    role = normalizeRole(u.role, Boolean(u.is_superuser));
  } catch (error) {
    throw new InvalidAccountRoleError(u.role, { cause: error });
  }

  return {
    id: u.id || null,
    name: u.name || u.username || '',
    username: u.username || '',
    email: u.email || '',
    phone: u.phone || u.phone_number || '',
    location: u.location || '',
    role,
    company_id: u.company_id || null,
    company_name: u.company_name || null,
    is_staff: Boolean(u.is_staff),
    is_superuser: Boolean(u.is_superuser),
    integrity_score: u.integrity_score ?? null,
  };
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(getStoredUser);
  const booting = false; // render from stored session; revalidate in background

  const save = (data) => {
    const normalized = normalizeUser(data);
    setUser(normalized);
    localStorage.setItem('user_session', JSON.stringify(normalized));
    return normalized;
  };

  useEffect(() => {
    if (!user) return undefined;
    let active = true;
    apiRequest('/users/profile/')
      .then((profile) => { if (active) save(profile); })
      .catch((e) => {
        // Only an explicit auth rejection ends the session; timeouts/5xx keep it.
        if (
          active &&
          (e?.status === 401 || e?.status === 403 || e instanceof InvalidAccountRoleError)
        ) {
          if (e instanceof InvalidAccountRoleError) {
            console.error('[AUTH] Invalid account profile; clearing the stale session.', e);
          }
          setUser(null);
          localStorage.removeItem('user_session');
        }
      });
    return () => { active = false; };
  }, []);

  const login = async (credentials) => save(await apiRequest('/users/login/', { method: 'POST', body: credentials }));
  const signup = async (credentials) => save(await apiRequest('/users/register/', { method: 'POST', body: credentials }));

  const logout = async () => {
    try { await apiRequest('/users/logout/', { method: 'POST' }); } finally {
      setUser(null);
      localStorage.removeItem('user_session');
    }
  };

  const value = useMemo(() => ({ user, login, signup, logout, booting, isAuthenticated: Boolean(user) }), [user, booting]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() { return useContext(AuthContext); }
