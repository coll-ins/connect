export const money = (v) =>
  `KES ${Number(v || 0).toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export const when = (v) =>
  v ? new Date(v).toLocaleString('en-KE', { dateStyle: 'medium', timeStyle: 'short' }) : '—';

export const label = (s) =>
  String(s || '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

export const localToIso = (v) => (v ? new Date(v).toISOString() : null);

export const localInput = (d) => {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};
