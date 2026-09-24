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

function normalizeRole(role, isSuperuser = false) {
  if (isSuperuser) return 'platform_admin';

  const value = String(role || 'passenger')
    .trim()
    .toLowerCase()
    .replace(/-/g, '_')
    .replace(/\s+/g, '_');

  if (value === 'platform_admin' || value === 'admin' || value === 'superadmin') {
    return 'platform_admin';
  }

  if (value === 'company_admin' || value === 'companyadmin') {
    return 'company_admin';
  }

  if (value === 'driver') {
    return 'driver';
  }

  return 'passenger';
}

function normalizeUser(data) {
  const u = data?.user || data || {};

  return {
    id: u.id || null,
    name: u.name || u.username || '',
    email: u.email || '',
    phone: u.phone || u.phone_number || '',
    location: u.location || '',
    role: normalizeRole(u.role, Boolean(u.is_superuser)),
    company_id: u.company_id || null,
    company_name: u.company_name || null,
    is_staff: Boolean(u.is_staff),
    is_superuser: Boolean(u.is_superuser),
    integrity_score: u.integrity_score ?? null,
  };
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(getStoredUser);
  const [booting, setBooting] = useState(true);

  const save = (data) => {
    const normalized = normalizeUser(data);
    setUser(normalized);
    localStorage.setItem('user_session', JSON.stringify(normalized));
    return normalized;
  };

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        if (user) {
          const profile = await apiRequest('/users/profile/');
          if (active) save(profile);
        }
      } catch {
        // A stale browser session is cleared only when the server rejects it.
        if (active && user) {
          setUser(null);
          localStorage.removeItem('user_session');
        }
      } finally {
        if (active) setBooting(false);
      }
    })();
    if (!user) setBooting(false);
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
