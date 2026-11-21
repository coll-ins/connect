import { newKey } from './idempotency.js';
import { formatMoney } from './money.js';
import { toCents } from './wallet.js';

// Same shape the server accepts. Min, max and the daily limit are the server's
// call; it answers with the numbers, so the form only checks the shape.
const AMOUNT = /^\d{1,7}(\.\d{1,2})?$/;
export function parseWithdrawAmount(raw) {
  const value = typeof raw === 'string' ? raw.trim() : '';
  if (!value) return { ok: false, error: 'Enter the amount you want to withdraw, in KES.' };
  if (!AMOUNT.test(value) || !(Number(value) > 0)) {
    return { ok: false, error: 'Enter an amount in KES above 0, with at most 2 decimals (for example 500 or 500.50).' };
  }
  return { ok: true, value };
}

export const isValidKey = (key) => typeof key === 'string' && /^[A-Za-z0-9_-]{8,64}$/.test(key);

const FINAL = ['paid', 'failed', 'review'];
export const isFinalStatus = (status) => FINAL.includes(status);

// One key per withdrawal intent (the amount in cents, so 500 and 500.00 match).
// A retry reuses it so the server replays instead of paying twice; it is only
// renewed once the payout reached a final state, or the server says it clashed.
export function createWithdrawKeys(generate = newKey) {
  let current = null;
  return {
    keyFor(amount) {
      const intent = toCents(amount);
      if (!current || current.intent !== intent) current = { intent, key: generate() };
      return current.key;
    },
    settle(status) {
      if (isFinalStatus(status)) current = null;
    },
    reset() {
      current = null;
    },
  };
}

const STATUS_COPY = {
  requested: { label: 'In progress', tone: 'info', text: 'We are sending this to your M-PESA number. It usually takes a few minutes.' },
  submitted: { label: 'In progress', tone: 'info', text: 'We are sending this to your M-PESA number. It usually takes a few minutes.' },
  paid: { label: 'Sent', tone: 'ok', text: 'The money was sent to your M-PESA number.' },
  failed: { label: 'Not sent', tone: 'warn', text: 'The transfer was refused, so nothing was sent. The money was returned to your wallet.' },
  review: { label: 'Under review', tone: 'info', text: 'We are checking this withdrawal; your money is safe. It will show here once we are done.' },
};
export function withdrawStatusCopy(status) {
  return STATUS_COPY[status] || { label: 'Status unavailable', tone: 'info', text: 'We could not read the status of this withdrawal. Check again in a moment.' };
}

const SAFE_RETRY = 'We could not confirm this withdrawal. It is safe to try again: it will not be sent twice. Check your history for the result.';

// text is plain copy, never the server's own words. field says where the
// message goes, kind is error | info | disabled, resetKey / refresh tell the
// caller what to do next.
export function withdrawErrorInfo(err) {
  const d = err?.data && typeof err.data === 'object' ? err.data : {};
  switch (d.code) {
    case 'feature_disabled': return { kind: 'disabled', text: 'Withdrawals are not available yet.' };
    case 'invalid_amount':
      return { kind: 'error', field: 'amount', text: 'Enter an amount in KES above 0, with at most 2 decimals.' };
    case 'amount_too_small':
      return { kind: 'error', field: 'amount', text: `The minimum withdrawal is ${formatMoney(d.min)}.` };
    case 'amount_too_large':
      return { kind: 'error', field: 'amount', text: `The maximum withdrawal is ${formatMoney(d.max)}.` };
    case 'insufficient_funds':
      return { kind: 'error', field: 'amount', refresh: true, text: 'Your wallet does not have enough money for this withdrawal. Try a smaller amount.' };
    case 'daily_limit':
      return {
        kind: 'error',
        field: 'amount',
        text: `You can withdraw up to ${formatMoney(d.limit)} in any 24 hours. You can still withdraw ${formatMoney(d.remaining)} now.`,
      };
    case 'password_required':
      return { kind: 'error', field: 'password', text: 'Enter your account password to confirm.' };
    case 'wrong_password':
      return { kind: 'error', field: 'password', text: 'That password is not correct. Try again.' };
    case 'too_many_attempts':
      return { kind: 'error', text: 'Too many wrong passwords. Withdrawals are locked for 15 minutes. Try again after that.' };
    case 'payout_in_flight':
      return { kind: 'info', refresh: true, text: 'You already have a withdrawal in progress. Wait for it to finish, then start a new one.' };
    case 'key_reused':
      return { kind: 'error', resetKey: true, text: 'That request was already used for a different amount. Check the amount and try again.' };
    case 'invalid_key':
      return { kind: 'error', resetKey: true, text: 'Something went wrong with this request. Please try again.' };
    case 'invalid_phone':
      return { kind: 'error', text: 'The phone number on your account cannot receive M-PESA. Update it in your profile, then try again.' };
    case 'destination_not_allowed':
      return { kind: 'error', text: 'Withdrawals can only go to your registered M-PESA number.' };
    case 'passenger_only':
      return { kind: 'error', text: 'Withdrawals are only for passenger accounts.' };
    default: break;
  }
  if (err?.status === 403) return { kind: 'error', text: 'Withdrawals are only for passenger accounts.' };
  if (err?.status === 429) {
    return { kind: 'error', text: 'Too many withdrawal requests. Wait a while and try again.' };
  }
  if (err?.status === 400) return { kind: 'error', text: 'We could not accept this withdrawal. Check the details and try again.' };
  return { kind: 'error', text: SAFE_RETRY };
}
