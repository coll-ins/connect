// What a field expects, and once something is typed, what is wrong with it.
// Pair with aria-describedby={id} and aria-invalid on the input.
export default function FieldNote({ id, hint, error, value }) {
  const show = Boolean(error) && String(value ?? '').trim() !== '';
  return (
    <small id={id} className={`field-note${show ? ' is-error' : ''}`} aria-live="polite">
      {show ? error : hint}
    </small>
  );
}
