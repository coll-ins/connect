import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ChevronLeft } from 'lucide-react';

// Back to the welcome screen, and one switch between the two ways in.
export default function AuthTopBar({ mode }) {
  const navigate = useNavigate();
  const { state } = useLocation();
  return (
    <>
      <button type="button" className="journey-back auth-back" onClick={() => navigate('/', { replace: true })}>
        <ChevronLeft size={20} aria-hidden="true" /> Back
      </button>
      <nav className="auth-switch" aria-label="Sign in or create an account">
        <Link to="/login" replace state={state} aria-current={mode === 'signin' ? 'page' : undefined}>Sign in</Link>
        <Link to="/signup" replace state={state} aria-current={mode === 'signup' ? 'page' : undefined}>Create account</Link>
      </nav>
    </>
  );
}
