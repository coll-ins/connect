import { useEffect, useRef, useState } from 'react';
import '../../legal/Legal.css';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { dashboardPath } from '../../utils/roleRoutes';
import PasswordInput from '../../components/PasswordInput';
import FieldNote from '../../components/FieldNote';
import { checkPhone, PHONE_HINT } from '../../utils/inputRules';
import AuthTopBar from './AuthTopBar';
import './Auth.css';
import '../../styles/forms.css';

// Only return to a page inside this user's own area.
function returnPath(user, from) {
  const home = dashboardPath(user);
  return typeof from === 'string' && (from === home || from.startsWith(`${home}/`))
    ? from
    : home;
}

export default function Login() {
  const { login, user: signedInUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [slowConnection, setSlowConnection] = useState(false);
  const phoneRef = useRef(null);

  useEffect(() => { document.title = 'Sign in | CONNECT'; }, []);

  useEffect(() => {
    if (!loading) {
      setSlowConnection(false);
      return undefined;
    }
    const timer = window.setTimeout(() => setSlowConnection(true), 1200);
    return () => window.clearTimeout(timer);
  }, [loading]);

  const submit = async (e) => {
    e.preventDefault();
    if (loading) return;
    setError('');
    setLoading(true);

    try {
      const user = await login({
        phone_number: phone.trim(),
        password,
      });

      navigate(returnPath(user, location.state?.from), { replace: true });
    } catch (err) {
      setError(err.message);
      phoneRef.current?.focus();
    } finally {
      setLoading(false);
    }
  };

  const phoneError = checkPhone(phone);

  // Already signed in on this device: go straight in.
  if (signedInUser) {
    return <Navigate to={returnPath(signedInUser, location.state?.from)} replace />;
  }

  return (
    <main className="auth-page">
      <div className="auth-card">
        <AuthTopBar mode="signin" />

        <h1>Sign in</h1>

        <p className="muted">
          Use the phone number and password you signed up with.
        </p>

        {error && <div id="login-error" className="error" role="alert">{error}</div>}

        <form onSubmit={submit} className="form-stack">
          <label>
            Phone number
            <input
              ref={phoneRef}
              type="tel"
              inputMode="tel"
              maxLength={16}
              className="input"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="07XX XXX XXX"
              autoComplete="tel"
              aria-describedby={error ? 'login-error li-phone' : 'li-phone'}
              aria-invalid={Boolean(error || (phone.trim() && phoneError)) || undefined}
              required
            />
          </label>
          <FieldNote id="li-phone" value={phone} error={phoneError} hint={PHONE_HINT} />

          <div className="form-field">
            <label htmlFor="login-password">Password</label>
            <PasswordInput
              id="login-password"
              className="input"
              aria-invalid={error ? 'true' : undefined}
              aria-describedby={error ? 'login-error' : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <button
            className="btn btn-primary btn-full"
            disabled={loading}
          >
            {loading ? (slowConnection ? 'Still connecting…' : 'Signing in…') : 'Sign in'}
          </button>
          {slowConnection && (
            <p role="status" className="muted">
              The free server can take up to 50 seconds to wake up. Keep this page open.
            </p>
          )}
        </form>

        <nav className="auth-legal" aria-label="Legal">
          <Link to="/legal/terms">Terms</Link>
          <Link to="/legal/privacy">Privacy</Link>
          <Link to="/legal/refunds">Refunds</Link>
        </nav>
      </div>
    </main>
  );
}
