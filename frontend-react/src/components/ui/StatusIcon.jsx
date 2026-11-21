import { Check, Clock3, LogIn, Undo2, X } from 'lucide-react';

// One distinct shape per status group, so colour is never the only signal.
const ICONS = { pending: Clock3, confirmed: Check, boarding: LogIn, cancelled: X, refunded: Undo2 };

export default function StatusIcon({ group, size = 12 }) {
  const Icon = ICONS[group];
  return Icon ? <Icon size={size} strokeWidth={2.5} aria-hidden="true" /> : null;
}
