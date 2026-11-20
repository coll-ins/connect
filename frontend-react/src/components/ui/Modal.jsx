import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { nextFocusIndex } from '../../utils/focusTrap';
import '../../styles/modal.css';

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

const FIELDS = 'input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled])';

const visible = (el) => el.getClientRects().length > 0;

/**
 * Shared dialog. Give it `labelledBy` (id of a heading inside it) or
 * `ariaLabel`, and an `onClose` that closes it. It renders the Close button.
 * Focus goes to the first field (else the first control), Tab stays inside,
 * Escape closes, focus returns to what opened it.
 */
export default function Modal({ labelledBy, ariaLabel, onClose, className = '', children }) {
  const dialogRef = useRef(null);
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; });

  useEffect(function focusAndTrap() {
    const dialog = dialogRef.current;
    const opener = document.activeElement;
    const target = [...dialog.querySelectorAll(FIELDS)].find(visible)
      || [...dialog.querySelectorAll(FOCUSABLE)].find(
        (el) => visible(el) && !el.classList.contains('modal-close'),
      )
      || dialog.querySelector('.modal-close')
      || dialog;
    target.focus();

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        closeRef.current?.();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = [...dialog.querySelectorAll(FOCUSABLE)].filter(visible);
      const next = nextFocusIndex(items.length, items.indexOf(document.activeElement), event.shiftKey);
      if (next === null) return;
      event.preventDefault();
      (items[next] || dialog).focus();
    };
    document.addEventListener('keydown', onKeyDown, true);

    return function returnFocus() {
      document.removeEventListener('keydown', onKeyDown, true);
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  // Rendered on the body: an animated page section would otherwise anchor this
  // "fixed" window to itself, leaving it down the page instead of on screen.
  return createPortal(
    <div className="modal-backdrop">
      <div
        ref={dialogRef}
        className={`modal ${className}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-label={labelledBy ? undefined : ariaLabel}
        tabIndex={-1}
      >
        <button type="button" className="btn btn-ghost modal-close" aria-label="Close" onClick={onClose}>
          Close
        </button>
        {children}
      </div>
    </div>,
    document.body,
  );
}
