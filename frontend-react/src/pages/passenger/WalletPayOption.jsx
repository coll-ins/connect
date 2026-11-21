import { useId } from 'react';
import { Link } from 'react-router-dom';
import { WalletCards } from 'lucide-react';
import { apiRequest } from '../../api';
import useAsyncData from '../../hooks/useAsyncData';
import { formatMoney } from '../../utils/money';
import { walletPayState } from '../../utils/wallet';
import './WalletPanels.css';

/**
 * "Pay from wallet" row for the pay modal. It loads the balance itself and
 * says why it is disabled; the modal owns the payment request, so one
 * in-flight guard covers every payment option.
 */
export default function WalletPayOption({ booking, busy, onPay, reloadKey }) {
  const reasonId = useId();
  const { status, data, reload } = useAsyncData(
    () => apiRequest('/wallet/', { silent: true }),
    [reloadKey],
  );
  const balance = status === 'ready' ? data?.available_balance : undefined;
  const { canPay, reason } = walletPayState({ balance, required: booking.total_amount });

  let hint = null;
  if (status === 'loading') hint = 'Checking your wallet balance…';
  else if (status === 'error') hint = 'We could not load your wallet balance.';
  else if (reason === 'insufficient') {
    hint = `Your wallet has ${formatMoney(balance)} but this booking costs ${formatMoney(booking.total_amount)}.`;
  }

  return (
    <div className="wallet-pay-option">
      <button
        type="button"
        className="pay-option"
        onClick={onPay}
        disabled={busy || !canPay}
        aria-describedby={reasonId}
      >
        <div className="pay-icon"><WalletCards size={20} aria-hidden="true" /></div>
        <div>
          <strong>Pay from wallet</strong>
          <span>Balance: {formatMoney(balance)}</span>
        </div>
      </button>
      <div id={reasonId} className="wallet-pay-reason" aria-live="polite">
        {hint}
        {status === 'error' && (
          <button type="button" className="btn btn-ghost" onClick={reload}>Retry</button>
        )}
        {reason === 'insufficient' && (
          <> <Link to="/passenger/wallet" className="wallet-link">Top up</Link></>
        )}
      </div>
    </div>
  );
}
