// A value that never loaded must not look like a balance: null, undefined,
// '' and non-numbers show "--", only a real number (including 0) shows KES.
export function formatMoney(value) {
  if (value === null || value === undefined || value === '') return '--';
  const n = Number(value);
  if (!Number.isFinite(n)) return '--';
  return `KES ${n.toLocaleString('en-KE', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

// Free-text amount from a form field -> a positive number with at most 2
// decimals, or null when it cannot be a payable amount.
export function parseMoneyInput(raw) {
  if (typeof raw !== 'string') return null;
  const cleaned = raw.replace(/KES/i, '').replace(/[\s,]/g, '');
  if (!/^\d+(\.\d+)?$/.test(cleaned)) return null;
  const n = Math.round(Number(cleaned) * 100) / 100;
  return n > 0 ? n : null;
}
