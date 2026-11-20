export function payCountdown(payBefore, now = Date.now()) {
  if (!payBefore) return null;
  const end = new Date(payBefore).getTime();
  if (!Number.isFinite(end)) return null;
  const left = Math.max(0, Math.ceil((end - now) / 1000));
  const m = Math.floor(left / 60);
  const s = String(left % 60).padStart(2, '0');
  return { expired: left === 0, text: `${m}:${s}` };
}

// After a gateway timeout, a 5xx or "payment already in progress" (409) the
// charge may exist: check its status instead of starting another one.
export function shouldCheckPaymentStatus(err) {
  const status = err?.status;
  return status === undefined || status === 409 || status >= 500;
}

export function bookingClosedMessage(err, locale = 'en-KE', timeZone) {
  if (err?.data?.code !== 'booking_closed') return null;
  const closes = err.data.closes_at ? new Date(err.data.closes_at) : null;
  if (closes && Number.isFinite(closes.getTime())) {
    const time = closes.toLocaleTimeString(locale, {
      hour: '2-digit', minute: '2-digit', hour12: false, timeZone,
    });
    return `Online booking for this trip closed at ${time}. Choose another departure.`;
  }
  return 'Online booking for this trip has closed. Choose another departure.';
}
