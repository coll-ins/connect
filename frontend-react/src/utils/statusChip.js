// Maps a booking, trip or payment status to one of the five status-colour groups
// (pending, confirmed, boarding, cancelled, refunded) or 'failed'. '' means no tint.
const GROUPS = {
  pending: ['pending', 'pending_payment', 'awaiting_payment', 'scheduled', 'processing'],
  confirmed: ['confirmed', 'paid', 'completed', 'delivered', 'settled'],
  boarding: ['boarding', 'boarded', 'in_progress', 'departed', 'picked_up'],
  cancelled: ['cancelled', 'canceled', 'expired', 'declined', 'rejected', 'no_show'],
  refunded: ['refunded'],
  failed: ['failed'],
};

export function statusGroup(status) {
  const key = String(status ?? '').trim().toLowerCase();
  return Object.keys(GROUPS).find((group) => GROUPS[group].includes(key)) || '';
}
