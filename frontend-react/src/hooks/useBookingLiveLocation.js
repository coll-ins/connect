import { useCallback, useEffect, useRef, useState } from 'react';
import { apiRequest } from '../api';

const POLL_INTERVAL = 10000;

export default function useBookingLiveLocation(bookingId, enabled = true) {
  const [liveLocation, setLiveLocation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const requestInFlight = useRef(false);
  const stopped = useRef(false);

  const refreshLocation = useCallback(async () => {
    if (!bookingId || !enabled || requestInFlight.current || stopped.current) {
      return;
    }

    requestInFlight.current = true;
    setLoading(true);

    try {
      const data = await apiRequest(
        `/bookings/${bookingId}/live-location/`,
      );

      setLiveLocation(data);
      setError('');
    } catch (err) {
      if ([403, 404, 409].includes(err.status)) {
        stopped.current = true;
        setLiveLocation(null);
      }
      setError(err.message || 'Unable to load live location.');
    } finally {
      requestInFlight.current = false;
      setLoading(false);
    }
  }, [bookingId, enabled]);

  useEffect(() => {
    if (!bookingId || !enabled) {
      setLiveLocation(null);
      setError('');
      return undefined;
    }

    stopped.current = false;
    refreshLocation();

    const interval = window.setInterval(
      refreshLocation,
      POLL_INTERVAL,
    );

    return () => {
      window.clearInterval(interval);
    };
  }, [bookingId, enabled, refreshLocation]);

  return {
    liveLocation,
    loading,
    error,
    refreshLocation,
  };
}
