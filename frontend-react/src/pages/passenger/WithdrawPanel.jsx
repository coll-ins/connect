import { useEffect, useMemo, useRef, useState } from 'react';
import { apiRequest } from '../../api';
import PasswordInput from '../../components/PasswordInput';
import AsyncPanel from '../../components/ui/AsyncPanel';
import Modal from '../../components/ui/Modal';
import useAsyncData from '../../hooks/useAsyncData';
import { formatMoney } from '../../utils/money';
import { toCents } from '../../utils/wallet';
import {
  createWithdrawKeys, parseWithdrawAmount, withdrawErrorInfo, withdrawStatusCopy,
} from '../../utils/withdraw';
import './WithdrawPanel.css';

const NONE = { amount: '', password: '' };

// The list answers 503 feature_disabled while payouts are off; that is a calm
// "not yet", not a failed load. Anything else keeps the Retry panel.
async function loadFirstPage() {
  try {
    const d = await apiRequest('/wallet/withdrawals/', { silent: true });
    const results = Array.isArray(d) ? d : (Array.isArray(d?.results) ? d.results : []);
    return { results, next: Array.isArray(d) ? null : (d?.next_cursor ?? null), disabled: false };
  } catch (e) {
    if (e?.data?.code === 'feature_disabled') return { results: [], next: null, disabled: true };
    throw e;
  }
}

const when = (iso) => (iso ? new Date(iso).toLocaleString('en-KE', { dateStyle: 'medium', timeStyle: 'short' }) : '');

function PayoutSummary({ payout }) {
  const copy = withdrawStatusCopy(payout.status);
  return (
    <>
      <strong>{formatMoney(payout.amount)}</strong>
      <span className={`withdraw-badge withdraw-${copy.tone}`}>{copy.label}</span>
      <span className="withdraw-dest">To {payout.destination_masked || 'your registered M-PESA number'}</span>
    </>
  );
}

function WithdrawHistory({ status, rows, next, onRetry, onRefresh, onMore, more }) {
  return (
    <div className="withdraw-history">
      <div className="withdraw-history-head">
        <h3 id="withdraw-history-title">Your withdrawals</h3>
        <button type="button" className="btn btn-ghost" onClick={onRefresh}>Check status</button>
      </div>
      <AsyncPanel status={status} title="your withdrawals" loadingText="Loading your withdrawals…" onRetry={onRetry}>
        {rows.length === 0 ? (
          <div className="glass-empty">
            <strong>No withdrawals yet.</strong>
            <span>Money you withdraw to M-PESA will show here.</span>
          </div>
        ) : (
          <ul className="wallet-history" aria-labelledby="withdraw-history-title">
            {rows.map((row) => {
              const copy = withdrawStatusCopy(row.status);
              return (
                <li key={row.payout_id}>
                  <div className="wallet-tx-main">
                    <strong>{formatMoney(row.amount)}</strong>
                    <time dateTime={row.created_at}>{when(row.created_at)}</time>
                    <span className="wallet-tx-ref">To {row.destination_masked || 'your M-PESA number'}</span>
                  </div>
                  <div className="wallet-tx-money">
                    <span className={`withdraw-badge withdraw-${copy.tone}`}>{copy.label}</span>
                    {row.status === 'failed' && <span>Returned to your wallet</span>}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {more.error && (
          <div className="async-panel async-panel-error" role="alert">
            <strong>Could not load more withdrawals</strong>
            <span>Check your connection and try again.</span>
          </div>
        )}
        {next && (
          <button type="button" className="btn btn-secondary withdraw-more" disabled={more.busy} onClick={onMore}>
            {more.busy ? 'Loading…' : 'Load more'}
          </button>
        )}
      </AsyncPanel>
    </div>
  );
}

/**
 * Withdraw to the account's own M-PESA number. Sends only amount, key and
 * password: the server picks the destination, so none is ever sent.
 */
export default function WithdrawPanel({ balance, onChanged }) {
  const [amount, setAmount] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState(NONE);
  const [notice, setNotice] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [off, setOff] = useState(false);
  const [pendingFocus, setPendingFocus] = useState('');
  const [more, setMore] = useState({ rows: [], next: undefined, busy: false, error: false });
  const keys = useMemo(() => createWithdrawKeys(), []);
  // A second click in the same tick runs before `busy` re-renders, so the
  // guard is a ref; busy only drives the labels.
  const inFlight = useRef(false);
  const amountRef = useRef(null);
  const passwordWrap = useRef(null);
  const changedRef = useRef(onChanged);
  useEffect(() => { changedRef.current = onChanged; });

  const first = useAsyncData(loadFirstPage);
  const reloadFirst = first.reload;
  const refresh = () => {
    setMore({ rows: [], next: undefined, busy: false, error: false });
    reloadFirst();
  };

  const firstRows = first.data?.results || [];
  const seen = new Set(firstRows.map((r) => r.payout_id));
  const rows = [...firstRows, ...more.rows.filter((r) => !seen.has(r.payout_id))];
  const next = more.next === undefined ? (first.data?.next ?? null) : more.next;
  const disabled = off || first.data?.disabled === true;
  // Until the first answer is in, the form would flash and vanish if payouts are off.
  const checking = first.status === 'loading' && !first.data && !off;
  const noBalance = toCents(balance) === 0;
  const destination = result?.destination_masked || firstRows[0]?.destination_masked;

  const focusField = (field) => {
    if (field === 'amount') amountRef.current?.focus();
    else passwordWrap.current?.querySelector('input')?.focus();
  };
  // After a server error the confirm dialog closes and hands focus back to its
  // opener in its own cleanup; this effect runs after that, so the field wins.
  useEffect(function focusAfterError() {
    if (!pendingFocus) return;
    focusField(pendingFocus);
    setPendingFocus('');
  }, [pendingFocus]);

  const review = (event) => {
    event.preventDefault();
    if (inFlight.current) return;
    setNotice(null);
    const parsed = parseWithdrawAmount(amount);
    if (!parsed.ok) {
      setErrors({ amount: parsed.error, password: '' });
      focusField('amount');
      return;
    }
    if (!password) {
      setErrors({ amount: '', password: 'Enter your account password to confirm.' });
      focusField('password');
      return;
    }
    setErrors(NONE);
    setConfirming(true);
  };

  const send = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setNotice(null);
    setResult(null);
    const body = { amount: amount.trim(), idempotency_key: keys.keyFor(amount), password };
    // Gone from state before the request leaves: success or failure, the
    // password is never kept.
    setPassword('');
    try {
      const data = await apiRequest('/wallet/withdraw/', { method: 'POST', body, silent: true });
      keys.settle(data.status);
      setResult(data);
      setAmount('');
      setConfirming(false);
      changedRef.current?.();
      refresh();
    } catch (e) {
      const info = withdrawErrorInfo(e);
      if (info.resetKey) keys.reset();
      setConfirming(false);
      if (info.kind === 'disabled') {
        setOff(true);
      } else if (info.field) {
        setErrors({ amount: '', password: '', [info.field]: info.text });
        setPendingFocus(info.field);
      } else {
        setNotice({ kind: info.kind, text: info.text });
      }
      if (info.refresh) { changedRef.current?.(); refresh(); }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const loadMore = async () => {
    if (more.busy || !next) return;
    setMore((m) => ({ ...m, busy: true, error: false }));
    try {
      const d = await apiRequest(`/wallet/withdrawals/?cursor=${encodeURIComponent(next)}`, { silent: true });
      const results = Array.isArray(d?.results) ? d.results : [];
      setMore((m) => ({ rows: [...m.rows, ...results], next: d?.next_cursor ?? null, busy: false, error: false }));
    } catch {
      setMore((m) => ({ ...m, busy: false, error: true }));
    }
  };

  const resultCopy = result ? withdrawStatusCopy(result.status) : null;
  const parsedAmount = parseWithdrawAmount(amount);

  return (
    <section className="wallet-section" aria-labelledby="withdraw-title">
      <h2 id="withdraw-title">Withdraw to M-PESA</h2>

      {checking ? (
        <p className="wallet-note" role="status">Checking withdrawals…</p>
      ) : disabled ? (
        <p className="wallet-note" role="status">Withdrawals are not available yet.</p>
      ) : (
        <>
          <p className="wallet-hint">
            Sent to your registered M-PESA number. Nothing is taken off: you receive the full amount.
          </p>
          {noBalance && (
            <p className="wallet-note" role="status">
              You have no money in your wallet to withdraw yet. Add money first, and it will be here when you are ready.
            </p>
          )}
          {result && (
            <div className={`withdraw-result withdraw-result-${resultCopy.tone}`} role="status">
              <PayoutSummary payout={result} />
              <p>{resultCopy.text}</p>
            </div>
          )}
          <form onSubmit={review} noValidate className="wallet-topup-form" autoComplete="off">
            <label htmlFor="withdraw-amount">How much to withdraw (KES)</label>
            <input
              id="withdraw-amount"
              ref={amountRef}
              className="input"
              type="text"
              inputMode="decimal"
              autoComplete="off"
              placeholder="500"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              aria-invalid={errors.amount ? 'true' : undefined}
              aria-describedby={errors.amount ? 'withdraw-amount-error' : undefined}
            />
            {errors.amount && <p id="withdraw-amount-error" className="wallet-field-error" role="alert">{errors.amount}</p>}

            <label htmlFor="withdraw-password">Account password</label>
            <div ref={passwordWrap}>
              <PasswordInput
                id="withdraw-password"
                className="input"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-invalid={errors.password ? 'true' : undefined}
                aria-describedby={errors.password ? 'withdraw-password-error' : 'withdraw-password-hint'}
              />
            </div>
            <p id="withdraw-password-hint" className="wallet-hint">We ask for it each time because this moves real money.</p>
            {errors.password && <p id="withdraw-password-error" className="wallet-field-error" role="alert">{errors.password}</p>}

            {notice && (
              <p className={notice.kind === 'info' ? 'wallet-note' : 'wallet-field-error'} role={notice.kind === 'info' ? 'status' : 'alert'}>
                {notice.text}
              </p>
            )}
            <button type="submit" className="btn btn-primary" disabled={busy}>Review withdrawal</button>
          </form>
        </>
      )}

      {confirming && parsedAmount.ok && (
        <Modal labelledBy="withdraw-confirm-title" onClose={() => { if (!inFlight.current) setConfirming(false); }}>
          <h2 id="withdraw-confirm-title">Confirm withdrawal</h2>
          <p className="withdraw-confirm-amount">{formatMoney(parsedAmount.value)}</p>
          <p className="wallet-hint">
            Sent to your registered M-PESA number{destination ? ` (${destination})` : ''}. You will receive the full amount.
          </p>
          <div className="wallet-actions">
            <button type="button" className="btn btn-primary" disabled={busy} onClick={send}>
              {busy ? 'Sending…' : 'Confirm withdrawal'}
            </button>
            <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </div>
        </Modal>
      )}

      <WithdrawHistory
        status={first.status}
        rows={rows}
        next={next}
        more={more}
        onRetry={reloadFirst}
        onRefresh={refresh}
        onMore={loadMore}
      />
    </section>
  );
}
