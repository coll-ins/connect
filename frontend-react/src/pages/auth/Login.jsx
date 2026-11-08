import { useEffect, useState } from 'react';
import '../../legal/Legal.css';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { dashboardPath } from '../../utils/roleRoutes';
import PasswordInput from '../../components/PasswordInput';

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
    } finally {
      setLoading(false);
    }
  };

  // Already signed in on this device: go straight in.
  if (signedInUser) {
    return <Navigate to={returnPath(signedInUser, location.state?.from)} replace />;
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="brand-mark">C</div>

        <p className="eyebrow">CONNECT matatu booking</p>

        <h1>Welcome back</h1>

        <p className="muted">
          Sign in to manage trips, bookings and payments.
        </p>

        {error && <div className="error">{error}</div>}

        <form onSubmit={submit} className="form-stack">
          <label>
            Phone number
            <input
              type="tel"
              className="input"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="07XX XXX XXX or +2547XX XXX XXX"
              autoComplete="tel"
              required
            />
          </label>

          <label>
            Password
            <PasswordInput
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>

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

        <p className="auth-footer">
          New to CONNECT? <Link to="/signup">Create an account</Link>
        </p>
        <nav className="auth-legal" aria-label="Legal">
          <Link to="/legal/terms">Terms</Link>
          <Link to="/legal/privacy">Privacy</Link>
          <Link to="/legal/refunds">Refunds</Link>
        </nav>
      </div>
    </div>
  );
}
