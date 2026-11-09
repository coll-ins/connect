import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { MapPin } from 'lucide-react';
import AppShell from '../../components/layout/AppShell';
import Notice, { NoticeStack } from '../../components/ui/Notice';
import PassengerLiveMap from './PassengerLiveMap';
import { apiRequest } from '../../api';

function endOfTrip(bookingStatus, tripStatus) {
  if (bookingStatus === 'no_show') {
    return {
      title: 'You missed this bus',
      detail: 'This booking was marked as a no-show.',
    };
  }

  if (bookingStatus === 'cancelled' || tripStatus === 'cancelled') {
    return {
      title: 'This trip was cancelled',
      detail: 'Check My bookings for your refund or another trip.',
    };
  }

  if (bookingStatus === 'completed' || tripStatus === 'completed') {
    return {
      title: 'You have arrived',
      detail: 'Your trip is complete. Thanks for riding with CONNECT.',
    };
  }

  return null;
}

export default function PassengerMapPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const requestedBookingId = searchParams.get('booking');
  const initialBooking = location.state?.booking;
  const hasInitialBooking =
    initialBooking &&
    String(initialBooking.booking_id || initialBooking.id) ===
      String(requestedBookingId);
  const [booking, setBooking] = useState(hasInitialBooking ? initialBooking : null);
  const bookingRef = useRef(hasInitialBooking ? initialBooking : null);
  const [bookingPending, setBookingPending] = useState(Boolean(hasInitialBooking));
  const [trackingAvailable, setTrackingAvailable] = useState(
    Boolean(
      hasInitialBooking &&
        (String(initialBooking.status || '').toLowerCase() === 'confirmed' ||
          (initialBooking.payment_method === 'cash' &&
            initialBooking.payment_status === 'pending')) &&
        ['boarding', 'departed'].includes(
          String(initialBooking.trip_status || '').toLowerCase(),
        ) &&
        initialBooking.driver_id,
    ),
  );
  const [loading, setLoading] = useState(!hasInitialBooking);
  const [error, setError] = useState('');
  const [loadFailed, setLoadFailed] = useState(false);
  const [ended, setEnded] = useState(null);
  const bookingLoadInProgress = useRef(false);
  const hasLoadedBooking = useRef(Boolean(hasInitialBooking));
  const updateBooking = useCallback((nextBooking) => {
    bookingRef.current = nextBooking;
    setBooking(nextBooking);
  }, []);

  const loadBooking = useCallback(async () => {
    if (bookingLoadInProgress.current) return;
    bookingLoadInProgress.current = true;

    try {
      if (!hasLoadedBooking.current) setLoading(true);
      setLoadFailed(false);

      const data = await apiRequest('/bookings/my/');
      const bookings = Array.isArray(data) ? data : [];

      const isTrackable = (item) => {
        const bookingStatus = String(item.status || '').toLowerCase();
        const tripStatus = String(item.trip_status || '').toLowerCase();

        // Cash on board holds the seat like a paid booking: the passenger
        // needs to see the bus to meet it and pay.
        const cashOnBoard =
          bookingStatus === 'pending' &&
          item.payment_method === 'cash' &&
          item.payment_status === 'pending';

        return (
          (bookingStatus === 'confirmed' ||
            cashOnBoard ||
            (bookingStatus === 'completed' && item.boarded === true)) &&
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
          const handoffBooking = bookingRef.current;
          if (
            handoffBooking &&
            String(handoffBooking.booking_id || handoffBooking.id) ===
              String(requestedBookingId)
          ) {
            setBookingPending(true);
            setTrackingAvailable(false);
            setError('');
            return;
          }

          setBookingPending(false);
          updateBooking(null);
          setTrackingAvailable(false);
          setError('That booking could not be found in your bookings.');
          return;
        }

        if (!isTrackable(exact)) {
          const bookingStatus = String(exact.status || '').toLowerCase();
          const tripStatus = String(exact.trip_status || '').toLowerCase();
          const isPendingCashReservation =
            exact.payment_method === 'cash' &&
            exact.payment_status === 'pending' &&
            bookingStatus === 'pending';
          if (
            (!isPendingCashReservation && bookingStatus !== 'confirmed') ||
            ['cancelled', 'completed', 'no_show'].includes(bookingStatus) ||
            ['completed', 'cancelled'].includes(tripStatus)
          ) {
            let message = 'This trip is not available for live tracking yet.';

            if (['cancelled', 'completed', 'no_show'].includes(bookingStatus)) {
              message = 'This booking is no longer active.';
            } else if (['completed', 'cancelled'].includes(tripStatus)) {
              message = tripStatus === 'completed'
                ? 'This trip has already been completed.'
                : 'This trip has been cancelled.';
            } else if (bookingStatus !== 'confirmed') {
              message = 'This booking is not confirmed.';
            }

            updateBooking(null);
            setBookingPending(false);
            setTrackingAvailable(false);
            setEnded(endOfTrip(bookingStatus, tripStatus));
            setError(message);
            return;
          }
        }

        updateBooking(exact);
        setBookingPending(false);
        setTrackingAvailable(isTrackable(exact));
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
        setBookingPending(false);
        updateBooking(null);
        setTrackingAvailable(false);
        setError(
          'You do not have an active trip to track yet. Live tracking is available once a confirmed trip is boarding or departed and has an assigned driver.',
        );
        return;
      }

      updateBooking(usable[0]);
      setBookingPending(false);
      setTrackingAvailable(true);
      setError('');
    } catch (err) {
      if (!hasLoadedBooking.current) {
        updateBooking(null);
        setTrackingAvailable(false);
      }
      setError(err.message || 'Unable to load your trips.');
      setLoadFailed(true);
    } finally {
      hasLoadedBooking.current = true;
      bookingLoadInProgress.current = false;
      setLoading(false);
    }
  }, [requestedBookingId, updateBooking]);

  useEffect(() => {
    loadBooking();
  }, [loadBooking]);

  useEffect(() => {
    if (!requestedBookingId || (!bookingPending && !booking)) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      if (!document.hidden) loadBooking();
    }, trackingAvailable ? 15000 : 5000);

    return () => window.clearInterval(timer);
  }, [booking, bookingPending, loadBooking, requestedBookingId, trackingAvailable]);

  if (loading) {
    return (
      <AppShell>
        <div className="passenger-page">
          <div className="glass-empty" role="status">Loading your trip…</div>
        </div>
      </AppShell>
    );
  }

  if (!booking) {
    return (
      <AppShell>
        <div className="passenger-page">
          <NoticeStack>
            {loadFailed && error && (
              <Notice title="We couldn't load your trip">
                {error}{' '}
                <button type="button" onClick={loadBooking}>
                  Try again
                </button>
              </Notice>
            )}
          </NoticeStack>
          <div className="glass-empty">
            <MapPin size={28} aria-hidden="true" />
            <strong>{ended?.title || 'No trip to track'}</strong>
            <span>
              {ended?.detail ||
                (loadFailed
                  ? 'Check your connection and try again.'
                  : 'Live tracking starts once a trip you booked is boarding or on the road.')}
            </span>
            <Link to="/passenger/bookings" className="glass-empty-action">
              My bookings
            </Link>
          </div>
        </div>
      </AppShell>
    );
  }

  return (
    <>
      {booking.payment_method === 'cash' &&
        booking.payment_status === 'pending' && (
          <div className="cn-notice cn-notice-info" role="status">
            <div className="cn-notice-body">
              <strong>Cash payment selected</strong>
              <span>
                Pay your fare in cash to the driver when you board and show
                your boarding PIN. The bus appears here once the trip is
                boarding and a driver is assigned.
              </span>
            </div>
          </div>
        )}
      <PassengerLiveMap
        bookingId={booking.booking_id || booking.id}
        bookingDetails={booking}
        onTripChange={loadBooking}
        trackingAvailable={trackingAvailable}
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
        onBack={() =>
          // Opened from the overview (directly or after paying): step back to
          // it, so one press leaves the map and history has no duplicate.
          location.state?.backToOverview && window.history.state?.idx > 0
            ? navigate(-1)
            : navigate('/passenger', { replace: true })
        }
      />
    </>
  );
}
