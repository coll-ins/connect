import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { dashboardPath } from '../../utils/roleRoutes';
import PasswordInput from '../../components/PasswordInput';
import '../../styles/forms.css';

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();

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
    setError('');
    setLoading(true);

    try {
      const user = await login({
        phone_number: phone.trim(),
        password,
      });

      navigate(dashboardPath(user), { replace: true });
    } catch (err) {
      setError(err.message);
      phoneRef.current?.focus();
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="auth-page">
      <div className="auth-card">
        <div className="brand-mark">C</div>

        <p className="eyebrow">CONNECT matatu booking</p>

        <h1>Welcome back</h1>

        <p className="muted">
          Sign in to manage trips, bookings and payments.
        </p>

        {error && <div id="login-error" className="error" role="alert">{error}</div>}

        <form onSubmit={submit} className="form-stack">
          <label>
            Phone number
            <input
              ref={phoneRef}
              type="tel"
              className="input"
              aria-invalid={error ? 'true' : undefined}
              aria-describedby={error ? 'login-error' : undefined}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="07XX XXX XXX or +2547XX XXX XXX"
              autoComplete="tel"
              required
            />
          </label>

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

        <p className="auth-footer">
          New to CONNECT? <Link to="/signup">Create an account</Link>
        </p>
      </div>
    </main>
  );
}
