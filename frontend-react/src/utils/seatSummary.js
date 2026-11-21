export const CUTOFF_MAX = 240;

// Same range the server enforces (0..240, whole minutes); the server stays the
// authority, this only saves a round trip on an obviously bad entry.
export function parseCutoff(raw) {
  const text = String(raw ?? '').trim();
  if (/^\d+$/.test(text)) {
    const n = Number(text);
    if (n <= CUTOFF_MAX) return { value: n, error: '' };
  }
  return { value: null, error: `Enter a whole number of minutes from 0 to ${CUTOFF_MAX}.` };
}

// Reason the walk-in form must stay off, from the server summary only.
// An unknown summary (still loading or failed) returns '' so the server's own
// check on submit decides.
export function walkInBlockReason(summary) {
  if (!summary) return '';
  if (summary.walkup_allowed === false) return 'Walk-up booking is not allowed for this trip.';
  if (Number(summary.open_seats) <= 0) return 'No seats are open on this trip.';
  return '';
}

// Whether the stage desk shows the walk-in form for a trip, from the server
// summary only. Boarding trips always show it (an unknown summary leaves the
// server to decide on submit). A scheduled trip shows it only once the server
// says walk-ups are allowed (past the online cut-off); while online booking is
// still open it shows the reason instead of hiding silently.
export function walkInDesk(status, summary) {
  const st = String(status || '').toLowerCase();
  if (st === 'boarding') return { showForm: true, reason: walkInBlockReason(summary) };
  if (st === 'scheduled' && summary) {
    return { showForm: summary.walkup_allowed === true, reason: walkInBlockReason(summary) };
  }
  return { showForm: false, reason: '' };
}
