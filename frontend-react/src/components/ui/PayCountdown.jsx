import { useEffect, useState } from 'react';
import { payCountdown } from '../../utils/payment';

/** "Pay within m:ss" for a pending booking; renders nothing without pay_before. */
export default function PayCountdown({ payBefore }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(function tick() {
    if (!payBefore) return undefined;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [payBefore]);

  const left = payCountdown(payBefore, now);
  if (!left) return null;
  return left.expired
    ? <p className="muted" role="status">The payment window has closed. This seat may be released.</p>
    : <p className="muted">Pay within <strong>{left.text}</strong> to keep your seat.</p>;
}
