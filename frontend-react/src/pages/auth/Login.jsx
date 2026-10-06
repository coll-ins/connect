import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { dashboardPath } from '../../utils/roleRoutes';

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

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
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="brand-mark">C</div>

        <p className="eyebrow">CONNECT • SMART MATATU TRAVEL</p>

        <h1>Welcome back</h1>

        <p className="muted">
          Sign in to manage trips, bookings and payments.
        </p>

        {error && <div className="error">{error}</div>}

        <form onSubmit={submit} className="form-stack">
          <label>
            Phone number
            <input
              className="input"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="07XX XXX XXX"
              autoComplete="tel"
              required
            />
          </label>

          <label>
            Password
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>

          <button
            className="btn btn-primary btn-full"
            disabled={loading}
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="auth-footer">
          New to CONNECT? <Link to="/signup">Create an account</Link>
        </p>
      </div>
    </div>
  );
}
