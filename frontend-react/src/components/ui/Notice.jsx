import { useEffect, useRef } from 'react';
import './Notice.css';

export function NoticeStack({ children }) {
  return <div className="cn-stack" aria-live="assertive">{children}</div>;
}

export default function Notice({ kind = 'error', title, children, onClose, autoHideMs = 0 }) {
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; });
  useEffect(() => {
    if (!autoHideMs) return undefined;
    const timer = setTimeout(() => closeRef.current?.(), autoHideMs);
    return () => clearTimeout(timer);
  }, [autoHideMs, children]);

  return (
    <div className={`cn-notice cn-notice-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      <span className="cn-notice-icon" aria-hidden="true">{kind === 'error' ? '!' : '✓'}</span>
      <div className="cn-notice-body">
        {title && <strong>{title}</strong>}
        <span>{children}</span>
      </div>
      {onClose && (
        <button type="button" className="cn-notice-close" aria-label="Dismiss message" onClick={onClose}>×</button>
      )}
    </div>
  );
}
