import { useEffect, useRef, useState } from 'react';
import { apiRequest } from '../../api';
import AsyncPanel from '../../components/ui/AsyncPanel';
import { formatMoney } from '../../utils/money';
import {
  TOPUP_POLL_MS, formatSigned, parseTopupAmount, topupErrorMessage, topupPollAction,
  topupReturnCopy, txTypeLabel,
} from '../../utils/wallet';
import './WalletPanels.css';

const FIELD_CODES = ['invalid_amount', 'amount_too_small', 'amount_too_large', 'balance_cap'];

export function TopUpForm() {
  const [amount, setAmount] = useState('');
  const [fieldError, setFieldError] = useState('');
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  // A second click in the same tick runs before `busy` re-renders, so the
  // guard is a ref; busy only drives the button label.
  const inFlight = useRef(false);
  const inputRef = useRef(null);

  const submit = async (event) => {
    event.preventDefault();
    if (inFlight.current) return;
    setNotice(null);
    const parsed = parseTopupAmount(amount);
    if (!parsed.ok) {
      setFieldError(parsed.error);
      inputRef.current?.focus();
      return;
    }
    setFieldError('');
    inFlight.current = true;
    setBusy(true);
    try {
      const data = await apiRequest('/wallet/topup/', {
        method: 'POST',
        body: { amount: parsed.value },
        silent: true,
      });
      // Stay busy while the browser leaves for the Paystack page.
      window.location.assign(data.authorization_url);
    } catch (e) {
      const text = topupErrorMessage(e);
      if (FIELD_CODES.includes(e?.data?.code)) {
        setFieldError(text);
        inputRef.current?.focus();
      } else {
        setNotice({ kind: e?.data?.code === 'topup_disabled' ? 'info' : 'error', text });
      }
      inFlight.current = false;
      setBusy(false);
    }
  };

  return (
    <section className="wallet-section" aria-labelledby="topup-title">
      <h2 id="topup-title">Add money</h2>
      <p className="wallet-hint">You will pay with M-PESA on a secure Paystack page, then come back here.</p>
      <form onSubmit={submit} noValidate className="wallet-topup-form">
        <label htmlFor="topup-amount">Amount (KES)</label>
        <input
          id="topup-amount"
          ref={inputRef}
          className="input"
          type="text"
          inputMode="decimal"
          autoComplete="off"
          placeholder="500"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          aria-invalid={fieldError ? 'true' : undefined}
          aria-describedby={fieldError ? 'topup-amount-error' : undefined}
        />
        {fieldError && <p id="topup-amount-error" className="wallet-field-error" role="alert">{fieldError}</p>}
        {notice && (
          <p
            className={notice.kind === 'info' ? 'wallet-note' : 'wallet-field-error'}
            role={notice.kind === 'info' ? 'status' : 'alert'}
          >
            {notice.text}
          </p>
        )}
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? 'Opening Paystack…' : 'Top up'}
        </button>
      </form>
    </section>
  );
}

/**
 * Shown after Paystack sends the passenger back with ?reference=. Polls until
 * the top-up reaches a final status, then asks the page to reload the balance.
 */
export function TopUpReturn({ reference, onCredited, onDone }) {
  const [view, setView] = useState({ kind: 'pending' });
  const [run, setRun] = useState(0);
  const creditedRef = useRef(onCredited);
  useEffect(() => { creditedRef.current = onCredited; });

  useEffect(function pollTopUp() {
    let active = true;
    let timer = null;
    let attempt = 0;
    const poll = async () => {
      attempt += 1;
      try {
        const data = await apiRequest(`/wallet/topup/${encodeURIComponent(reference)}/`, { silent: true });
        if (!active) return;
        const action = topupPollAction(data.status, attempt);
        if (action === 'continue') {
          timer = window.setTimeout(poll, TOPUP_POLL_MS);
          return;
        }
        setView({ kind: action, amount: data.amount });
        if (action === 'credited') creditedRef.current?.();
      } catch (e) {
        if (!active) return;
        setView({ kind: 'error', missing: e?.status === 403 || e?.status === 404 });
      }
    };
    poll();
    return function stopPolling() {
      active = false;
      window.clearTimeout(timer);
    };
  }, [reference, run]);

  const recheck = () => {
    setView({ kind: 'pending' });
    setRun((n) => n + 1);
  };

  const { kind } = view;
  const done = kind !== 'pending';
  let title = 'Checking your top-up';
  let text = topupReturnCopy('pending');
  if (kind === 'credited' || kind === 'review' || kind === 'expired') {
    title = { credited: 'Top-up received', review: 'Top-up under review', expired: 'Top-up expired' }[kind];
    text = topupReturnCopy(kind, view.amount);
  } else if (kind === 'giveup') {
    title = 'Still waiting';
    text = 'We have not heard back from M-PESA yet. If you were charged, the money will be added once it arrives.';
  } else if (kind === 'error') {
    title = 'Could not check this top-up';
    text = view.missing
      ? 'We could not find this top-up on your account.'
      : 'We could not reach CONNECT to check your top-up. Check your connection and try again.';
  }

  return (
    <section className="wallet-section wallet-return" aria-labelledby="topup-return-title" aria-busy={!done}>
      <h2 id="topup-return-title">{title}</h2>
      <p role="status">{text}</p>
      <div className="wallet-actions">
        {(kind === 'giveup' || (kind === 'error' && !view.missing)) && (
          <button type="button" className="btn btn-secondary" onClick={recheck}>Check again</button>
        )}
        {done && <button type="button" className="btn btn-ghost" onClick={onDone}>Dismiss</button>}
      </div>
    </section>
  );
}

export function WalletHistory({ status, rows, onRetry }) {
  const list = Array.isArray(rows) ? rows : [];
  return (
    <section className="wallet-section" aria-labelledby="history-title">
      <h2 id="history-title">History</h2>
      <AsyncPanel status={status} title="your wallet history" loadingText="Loading your history…" onRetry={onRetry}>
        {list.length === 0 ? (
          <div className="glass-empty">
            <strong>No wallet activity yet.</strong>
            <span>Top-ups, booking payments and refunds show up here.</span>
          </div>
        ) : (
          <ul className="wallet-history">
            {list.map((row) => {
              const amount = formatSigned(row.amount);
              return (
                <li key={row.id}>
                  <div className="wallet-tx-main">
                    <strong>{txTypeLabel(row.type)}</strong>
                    <time dateTime={row.created_at}>
                      {row.created_at ? new Date(row.created_at).toLocaleString('en-KE', { dateStyle: 'medium', timeStyle: 'short' }) : ''}
                    </time>
                    {row.reference && <span className="wallet-tx-ref">Ref {row.reference}</span>}
                  </div>
                  <div className="wallet-tx-money">
                    <strong className={amount.sign === '-' ? 'wallet-debit' : 'wallet-credit'}>
                      <span aria-hidden="true">{amount.text}</span>
                      <span className="wallet-sr">{amount.words}</span>
                    </strong>
                    <span>Balance {formatMoney(row.balance_after)}</span>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </AsyncPanel>
    </section>
  );
}

