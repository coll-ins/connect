import { useEffect, useId, useRef } from 'react';
import FieldNote from './FieldNote';

// An input (or textarea) that shows what it expects and, when `error` is set,
// stops its form from submitting with that message.
export default function ValidatedInput({ as: Tag = 'input', hint, error, ...props }) {
  const noteId = useId();
  const ref = useRef(null);
  useEffect(() => { ref.current?.setCustomValidity(error || ''); }, [error]);
  return (
    <>
      <Tag ref={ref} {...props}
        aria-describedby={noteId}
        aria-invalid={Boolean(error && String(props.value ?? '').trim())} />
      <FieldNote id={noteId} hint={hint} error={error} value={props.value} />
    </>
  );
}
