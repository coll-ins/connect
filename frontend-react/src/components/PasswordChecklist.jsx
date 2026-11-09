import { Check, X } from 'lucide-react';

// Same rules as backend users/validators.py PasswordComplexityValidator.
export const PASSWORD_RULES = [
  { label: 'At least 8 characters', test: (p) => p.length >= 8 },
  { label: 'One uppercase letter (A–Z)', test: (p) => /[A-Z]/.test(p) },
  { label: 'One lowercase letter (a–z)', test: (p) => /[a-z]/.test(p) },
  { label: 'One number (0–9)', test: (p) => /[0-9]/.test(p) },
  { label: 'One special character (! @ # - …)', test: (p) => /[^A-Za-z0-9]/.test(p) },
];

export const passwordIsStrong = (p) => PASSWORD_RULES.every((r) => r.test(p));

export default function PasswordChecklist({ password, id }) {
  return (
    <ul className="pw-checklist" id={id} aria-live="polite">
      {PASSWORD_RULES.map((rule) => {
        const ok = rule.test(password);
        return (
          <li key={rule.label} className={ok ? 'is-met' : ''}>
            {ok ? <Check size={16} aria-hidden="true" /> : <X size={16} aria-hidden="true" />}
            <span>{rule.label}</span>
            <span className="sr-only">{ok ? ' — done' : ' — missing'}</span>
          </li>
        );
      })}
    </ul>
  );
}
