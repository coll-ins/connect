import '../../styles/states.css';
/**
 * loading | error | ready wrapper for one list or panel.
 * Children render only when `status` is 'ready', so a failed or pending load
 * can never show an empty list or a zero balance.
 */
export default function AsyncPanel({
  status,
  onRetry,
  title = 'this page',
  loadingText = 'Loading…',
  errorTitle,
  children,
}) {
  if (status === 'ready') return children;

  if (status === 'error') {
    return (
      <div className="async-panel async-panel-error" role="alert">
        <strong>{errorTitle || `Could not load ${title}`}</strong>
        <span>Check your connection and try again.</span>
        {onRetry && (
          <button type="button" className="btn btn-secondary" onClick={onRetry}>Retry</button>
        )}
      </div>
    );
  }

  return (
    <div className="async-panel glass-empty" role="status" aria-busy="true">
      {loadingText}
    </div>
  );
}
