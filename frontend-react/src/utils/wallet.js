import { formatMoney } from './money.js';

// The server re-queries Paystack for a pending top-up with a 5 s cooldown per
// reference, so polling faster only returns the same answer.
export const TOPUP_POLL_MS = 5000;
export const TOPUP_POLL_MAX = 12;

// Same shape the server accepts (1-7 digits, up to 2 decimals, above zero).
// Min, max and the balance cap are the server's call; it answers with the
// numbers, so the form does not guess them.
const AMOUNT = /^\d{1,7}(\.\d{1,2})?$/;
export function parseTopupAmount(raw) {
  const value = typeof raw === 'string' ? raw.trim() : '';
  if (!value) return { ok: false, error: 'Enter the amount you want to add, in KES.' };
  if (!AMOUNT.test(value) || !(Number(value) > 0)) {
    return { ok: false, error: 'Enter an amount in KES above 0, with at most 2 decimals (for example 500 or 500.50).' };
  }
  return { ok: true, value };
}

// Whole cents as an integer, so balance versus fare never hits float drift.
export function toCents(value) {
  if (typeof value !== 'string' && typeof value !== 'number') return null;
  const s = String(value).trim();
  if (!/^-?\d+(\.\d{1,2})?$/.test(s)) return null;
  return Math.round(Number(s) * 100);
}

export function walletPayState({ balance, required }) {
  const have = toCents(balance);
  const need = toCents(required);
  if (have === null || need === null) return { canPay: false, reason: 'unknown' };
  if (have < need) return { canPay: false, reason: 'insufficient' };
  return { canPay: true, reason: null };
}

const NOT_CHARGED = 'Check your connection and try again. You will not be charged twice.';

export function topupErrorMessage(err) {
  const d = err?.data && typeof err.data === 'object' ? err.data : {};
  switch (d.code) {
    case 'topup_disabled': return 'Top-up is not available yet.';
    case 'invalid_amount': return 'Enter an amount in KES above 0, with at most 2 decimals.';
    case 'amount_too_small': return `The minimum top-up is ${formatMoney(d.min)}.`;
    case 'amount_too_large': return `The maximum top-up is ${formatMoney(d.max)}.`;
    case 'balance_cap':
      return `Your wallet can hold at most ${formatMoney(d.max_balance)}. Your balance is ${formatMoney(d.balance)}, so add a smaller amount.`;
    case 'passenger_only': return 'Wallet top-up is only for passenger accounts.';
    case 'gateway_error': return 'We could not reach the payment provider. You were not charged. Try again in a moment.';
    default: break;
  }
  if (err?.status === 403) return 'Wallet top-up is only for passenger accounts.';
  if (err?.status === 429) return 'Too many top-up attempts. Wait a little and try again.';
  if (err?.status === undefined) return 'We could not reach CONNECT. Check your connection and try again.';
  return 'We could not start the top-up. Try again in a moment.';
}

// text is the plain copy; refreshBooking / refreshWallet tell the caller what
// went stale so it can reload instead of leaving old numbers on screen.
export function walletPayErrorMessage(err) {
  const d = err?.data && typeof err.data === 'object' ? err.data : {};
  switch (d.code) {
    case 'insufficient_funds':
      return {
        text: `Your wallet has ${formatMoney(d.balance)} but this booking costs ${formatMoney(d.required)}. Top up first.`,
        refreshWallet: true,
      };
    case 'amount_mismatch':
      return { text: 'The price changed. Close this window and open the booking again.', refreshBooking: true };
    case 'booking_not_payable':
      return { text: 'This booking can no longer be paid. Check your bookings.', refreshBooking: true };
    case 'trip_departed':
      return { text: 'This trip has already departed, so it cannot be paid for.', refreshBooking: true };
    case 'passenger_only':
      return { text: 'Paying from the wallet is only for passenger accounts.' };
    case 'already_paid':
      return { text: 'This booking is already paid. Nothing was taken from your wallet.', refreshBooking: true };
    case 'hold_expired':
      return { text: 'The payment window for this seat closed. Nothing was taken from your wallet.', refreshBooking: true };
    case 'booking_moved':
      return { text: 'This booking was moved to another trip. Nothing was taken from your wallet.', refreshBooking: true };
    case 'hold_conflict':
      return { text: 'Something else is updating this booking. Try again in a moment.' };
    default: break;
  }
  if (err?.status === 404) return { text: 'We could not find this booking. Check your bookings.', refreshBooking: true };
  if (err?.status === 403) return { text: 'Paying from the wallet is only for passenger accounts.' };
  if (err?.status === 429) return { text: 'Too many attempts. Wait a little and try again.' };
  // The server replays a repeat of the same spend, so retrying is safe.
  return { text: NOT_CHARGED };
}

const TERMINAL = ['credited', 'review', 'expired'];
export function topupPollAction(status, attempt) {
  if (TERMINAL.includes(status)) return status;
  return attempt >= TOPUP_POLL_MAX ? 'giveup' : 'continue';
}

export function topupReturnCopy(status, amount) {
  switch (status) {
    case 'credited': return `${formatMoney(amount)} was added to your wallet.`;
    case 'review': return 'We received your payment and are checking it. It will show in your history once it is credited.';
    case 'expired': return 'This top-up expired; if you were charged it will be credited.';
    default: return 'We are confirming your payment with M-PESA. This usually takes under a minute.';
  }
}

export function formatSigned(amount) {
  const cents = toCents(amount);
  if (cents === null || cents === 0) return { sign: '', text: '--', words: 'Amount unavailable' };
  const abs = formatMoney(Math.abs(cents) / 100);
  return cents > 0
    ? { sign: '+', text: `+${abs}`, words: `Credit of ${abs}` }
    : { sign: '-', text: `-${abs}`, words: `Debit of ${abs}` };
}

const TYPE_LABELS = {
  deposit: 'Top-up',
  spend: 'Booking payment',
  refund: 'Refund',
  withdrawal: 'Withdrawal',
  withdrawal_reversal: 'Withdrawal returned',
};
export const txTypeLabel = (type) => TYPE_LABELS[type] || 'Wallet activity';

export function cancelWarning(booking) {
  const pay = String(booking?.payment_status || '').toLowerCase();
  const method = String(booking?.payment_method || '').toLowerCase();
  if (pay !== 'confirmed' || method === 'cash') return 'Cancel this booking? Nothing has been charged.';
  if (method === 'wallet') {
    return 'Cancel this booking? 50% of the fare goes back to your CONNECT wallet at once.';
  }
  return 'Cancel this booking? You will be refunded 50% of the fare.';
}
