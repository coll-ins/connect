// A list endpoint can answer with an array, a paged { results }, or (when the
// server misbehaves) something else entirely. Screens must never crash on it.
export const asList = (value) => {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.results)) return value.results;
  return [];
};

export function normalizeOperatorRoutes(res) {
  const operators = asList(res?.operators).map((op) => ({
    ...op,
    route_ids: asList(op?.route_ids),
  }));
  return { routes: asList(res?.routes), operators };
}

export const findCompany = (list, companyId) =>
  asList(list).find((item) => Number(item?.id) === Number(companyId)) || null;

export const staffOfCompany = (list, companyId) =>
  asList(list).filter((item) => Number(item?.company) === Number(companyId));

// The server counts held and confirmed seats the same way the walk-in check
// does; only fall back to adding bookings up in the browser when it is absent.
export function bookedSeatsOf(trip, fallback = 0) {
  const server = trip?.booked_seats;
  if (server === null || server === undefined || server === '') return fallback;
  const n = Number(server);
  return Number.isFinite(n) ? n : fallback;
}
