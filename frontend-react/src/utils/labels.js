// Raw API codes (no_show, company_auditor) must never reach a screen.
const SPECIAL = {
  no_show: 'No-show',
  platform_admin: 'Platform admin',
  company_manager: 'Company manager',
  company_auditor: 'Company auditor',
  company_operator: 'Company operator',
};

export function humanLabel(value) {
  const raw = String(value ?? '').trim();
  if (!raw) return '';
  const key = raw.toLowerCase();
  if (SPECIAL[key]) return SPECIAL[key];
  const words = key.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}
