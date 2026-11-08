import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import Notice, { NoticeStack } from '../../components/ui/Notice';
import { apiRequest } from '../../api';

export default function PaymentReturn() {
  const { bookingId } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const reference = params.get('reference');
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState('checking');
  const [message, setMessage] = useState('Confirming your payment securely…');

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const mapPageReady = import('./PassengerMapPage').then(
          () => true,
          () => false,
        );
        const [data, bookings] = await Promise.all([
          apiRequest(
            `/bookings/payments/${bookingId}/verify/`,
            { method: 'POST', body: { reference } },
          ),
          apiRequest('/bookings/my/'),
        ]);
        if (!active) return;

        if (data.payment_status === 'confirmed') {
          if (!(await mapPageReady)) {
            if (!active) return;
            setStatus('map-error');
            setMessage(
              'Your payment is confirmed, but the map did not load. Please try again or open this trip from your passenger dashboard.',
            );
            return;
          }
          const booking = Array.isArray(bookings)
            ? bookings.find(
                (item) => String(item.booking_id || item.id) === String(bookingId),
              )
            : null;
          // Under the map sits the overview, so leaving the map never goes
          // back to this page or the payment provider.
          navigate('/passenger', { replace: true });
          navigate(`/passenger/map?booking=${encodeURIComponent(bookingId)}`, {
            state: {
              booking: booking
                ? {
                    ...booking,
                    status: data.booking_status || booking.status,
                    payment_status: 'confirmed',
                  }
                : null,
            },
          });
          return;
        }

        setStatus('pending');
        setMessage(
          data.message ||
            'Your payment is still being confirmed. Check your bookings again in a moment.',
        );
      } catch (error) {
        if (!active) return;
        setStatus('error');
        setMessage(error.message || 'We could not confirm your payment. Please try again.');
      }
    })();

    return () => {
      active = false;
    };
  }, [attempt, bookingId, navigate, reference]);

  return (
    <div className="auth-page">
      {(status === 'error' || status === 'map-error') && (
        <NoticeStack>
          <Notice
            title={status === 'map-error' ? 'Payment confirmed' : 'Payment check failed'}
          >
            {message}
          </Notice>
        </NoticeStack>
      )}
      <div className="auth-card payment-status">
        <div style={{ fontSize: 52 }} aria-hidden="true">
          {status === 'error' || status === 'map-error'
            ? '!'
            : status === 'pending'
              ? '…'
              : '⌛'}
        </div>
        <p className="eyebrow">CONNECT payment</p>
        <h1>
          {status === 'map-error'
            ? 'Payment confirmed'
            : status === 'error'
            ? 'Payment check failed'
            : status === 'pending'
              ? 'Payment is still processing'
              : 'Checking payment'}
        </h1>
        <p className="muted">{message}</p>
        {status === 'error' || status === 'map-error' ? (
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setStatus('checking');
              setMessage('Confirming your payment securely...');
              setAttempt((value) => value + 1);
            }}
          >
            Try again
          </button>
        ) : (
          <Link className="btn btn-primary" to="/passenger">
            Back to passenger dashboard
          </Link>
        )}
      </div>
    </div>
  );
}
