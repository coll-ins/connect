const WORDS = {
  'company-manager': 'Company manager',
  'company-auditor': 'Company auditor',
  'company-operator': 'Company operator',
  'platform-admin': 'Platform admin',
  'route-planner': 'Route planner',
};

const label = (segment) => {
  const text = WORDS[segment] || segment.replace(/-/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
};

// Last static segment names the page; ids ("/payment/12") fall back to the
// segment before them.
export function titleForPath(pathname) {
  const parts = String(pathname || '').split('/').filter(Boolean);
  const named = parts.filter((p) => !/^\d+$/.test(p));
  const last = named[named.length - 1];
  return last ? `${label(last)} | CONNECT` : 'CONNECT';
}
