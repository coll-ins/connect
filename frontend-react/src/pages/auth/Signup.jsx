import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';

export default function Signup() {
  const { signup } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ phone_number: '', password: '', location: '' });
  const [error, setError] = useState(''); const [loading, setLoading] = useState(false);
  const update = (key) => (e) => setForm(v => ({ ...v, [key]: e.target.value }));
  const submit = async (e) => {
    e.preventDefault(); setError(''); setLoading(true);
    try { await signup(form); navigate('/passenger'); } catch (err) { setError(err.message); } finally { setLoading(false); }
  };
  return <div className="auth-page"><div className="auth-card">
    <div className="brand-mark">C</div><p className="eyebrow">JOIN CONNECT</p><h1>Create your account</h1><p className="muted">Book rides quickly and keep every trip in one place.</p>
    {error && <div className="error">{error}</div>}
    <form onSubmit={submit} className="form-stack">
      <label>Phone number<input className="input" value={form.phone_number} onChange={update('phone_number')} placeholder="07XX XXX XXX" required /></label>
      <label>Usual location<input className="input" value={form.location} onChange={update('location')} placeholder="e.g. CBD" /></label>
      <label>Password<input className="input" type="password" minLength="6" value={form.password} onChange={update('password')} required /></label>
      <button className="btn btn-primary btn-full" disabled={loading}>{loading ? 'Creating…' : 'Create account'}</button>
    </form>
    <p className="auth-footer">Already registered? <Link to="/login">Sign in</Link></p>
  </div></div>;
}
