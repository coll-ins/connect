import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import PassengerLiveMap from './PassengerLiveMap';
import { apiRequest } from '../../api';

export default function PassengerMapPage() {
  const [searchParams] = useSearchParams();
  const requestedBookingId = searchParams.get('booking');
  const [booking, setBooking] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadBooking = useCallback(async () => {
    try {
      setLoading(true);

      const data = await apiRequest('/bookings/my/');
      const bookings = Array.isArray(data) ? data : [];

      const isTrackable = (item) => {
        const bookingStatus = String(item.status || '').toLowerCase();
        const tripStatus = String(item.trip_status || '').toLowerCase();

        return (
          bookingStatus === 'confirmed' &&
          ['boarding', 'departed'].includes(tripStatus) &&
          Boolean(item.driver_id)
        );
      };

      // An explicit booking request must never fall through to another trip.
      if (requestedBookingId) {
        const exact = bookings.find(
          (item) =>
            String(item.booking_id || item.id) === String(requestedBookingId),
        );

        if (!exact) {
          setBooking(null);
          setError('That booking could not be found in your bookings.');
          return;
        }

        if (!isTrackable(exact)) {
          const bookingStatus = String(exact.status || '').toLowerCase();
          const tripStatus = String(exact.trip_status || '').toLowerCase();

          let message = 'This trip is not available for live tracking yet.';

          if (['cancelled', 'completed', 'no_show'].includes(bookingStatus)) {
            message = 'This booking is no longer active.';
          } else if (['completed', 'cancelled'].includes(tripStatus)) {
            message = tripStatus === 'completed'
              ? 'This trip has already been completed.'
              : 'This trip has been cancelled.';
          } else if (bookingStatus !== 'confirmed') {
            message = 'This booking is not confirmed.';
          } else if (!['boarding', 'departed'].includes(tripStatus)) {
            message = 'Live tracking becomes available when the trip starts boarding or departs.';
          } else if (!exact.driver_id) {
            message = 'A driver has not yet been assigned to this trip.';
          }

          setBooking(null);
          setError(message);
          return;
        }

        setBooking(exact);
        setError('');
        return;
      }

      // Without an explicit booking ID, select only an eligible live trip.
      const usable = bookings
        .filter(isTrackable)
        .sort((a, b) => {
          const aTime = a.departure_at
            ? new Date(a.departure_at).getTime()
            : Number.MAX_SAFE_INTEGER;

          const bTime = b.departure_at
            ? new Date(b.departure_at).getTime()
            : Number.MAX_SAFE_INTEGER;

          return aTime - bTime;
        });

      if (!usable.length) {
        setBooking(null);
        setError(
          'You do not have an active trip to track yet. Live tracking is available once a confirmed trip is boarding or departed and has an assigned driver.',
        );
        return;
      }

      setBooking(usable[0]);
      setError('');
    } catch (err) {
      setBooking(null);
      setError(err.message || 'Unable to load your trips.');
    } finally {
      setLoading(false);
    }
  }, [requestedBookingId]);

  useEffect(() => {
    loadBooking();
  }, [loadBooking]);

  if (loading) {
    return (
      <div
        style={{
          minHeight: '100dvh',
          display: 'grid',
          placeItems: 'center',
          background: '#f1f5f9',
          color: '#475569',
          fontWeight: 700,
        }}
      >
        Loading your trip…
      </div>
    );
  }

  if (!booking) {
    return (
      <div
        style={{
          minHeight: '100dvh',
          display: 'grid',
          placeItems: 'center',
          padding: 24,
          background: '#f1f5f9',
        }}
      >
        <div
          style={{
            width: 'min(420px, 100%)',
            padding: 28,
            borderRadius: 24,
            background: '#fff',
            boxShadow: '0 20px 50px rgba(15,23,42,.12)',
            textAlign: 'center',
          }}
        >
          <div style={{ fontSize: 42, marginBottom: 12 }}>🚌</div>

          <h2 style={{ margin: '0 0 8px', color: '#0f172a' }}>
            No trip to track
          </h2>

          <p style={{ margin: '0 0 20px', color: '#64748b' }}>
            {error || 'Book a trip first to see its live location.'}
          </p>

          <button
            type="button"
            onClick={() => window.history.back()}
            style={{
              border: 0,
              borderRadius: 12,
              padding: '11px 18px',
              background: '#111827',
              color: '#fff',
              fontWeight: 800,
              cursor: 'pointer',
            }}
          >
            Go back
          </button>
        </div>
      </div>
    );
  }

  return (
    <PassengerLiveMap
      bookingId={booking.booking_id || booking.id}
      routeGeometry={
        booking.route_geometry ||
        booking.trip?.route_geometry ||
        booking.trip_details?.route_geometry ||
        booking.route?.geometry ||
        booking.trip?.route?.geometry ||
        null
      }
      pickup={{
        latitude:
          booking.pickup_latitude ??
          booking.pickup_stage_latitude ??
          booking.pickup_stage?.latitude ??
          null,
        longitude:
          booking.pickup_longitude ??
          booking.pickup_stage_longitude ??
          booking.pickup_stage?.longitude ??
          null,
        name:
          booking.pickup_stage_name ||
          booking.pickup_stage?.name ||
          booking.pickup_location ||
          'Pickup stage',
        id:
          booking.pickup_stage_id ??
          booking.pickup_stage?.id ??
          null,
      }}
      onBack={() => window.history.back()}
    />
  );
}
