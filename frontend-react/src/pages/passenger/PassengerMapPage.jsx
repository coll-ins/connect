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

      // A booking the passenger tapped is shown as-is, whatever its
      // departure time or status (only cancelled ones are skipped).
      if (requestedBookingId) {
        const exact = bookings.find(
          (item) =>
            String(item.booking_id || item.id) === String(requestedBookingId) &&
            String(item.status || '').toLowerCase() !== 'cancelled',
        );

        if (exact) {
          setBooking(exact);
          setError('');
          return;
        }
      }

      const now = Date.now();

      const usable = bookings
        .filter((item) => {
          if (
            requestedBookingId &&
            String(item.booking_id || item.id) !== String(requestedBookingId)
          ) {
            return false;
          }

          const status = String(item.status || '').toLowerCase();

          if (['cancelled', 'completed'].includes(status)) {
            return false;
          }

          const departureValue =
            item.departure_at ||
            item.trip?.departure_at ||
            item.trip_details?.departure_at;

          if (!departureValue) {
            return status === 'active' || status === 'confirmed';
          }

          const departure = new Date(departureValue).getTime();

          return (
            departure >= now ||
            status === 'active' ||
            status === 'confirmed'
          );
        })
        .sort((a, b) => {
          const aValue =
            a.departure_at ||
            a.trip?.departure_at ||
            a.trip_details?.departure_at;

          const bValue =
            b.departure_at ||
            b.trip?.departure_at ||
            b.trip_details?.departure_at;

          const aTime = aValue
            ? new Date(aValue).getTime()
            : Number.MAX_SAFE_INTEGER;

          const bTime = bValue
            ? new Date(bValue).getTime()
            : Number.MAX_SAFE_INTEGER;

          return aTime - bTime;
        });

      if (!usable.length) {
        setBooking(null);
        setError('You do not have an upcoming trip to track yet.');
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
