import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import PasswordInput from '../../components/PasswordInput';
import { dashboardPath } from '../../utils/roleRoutes';
import '../../legal/Legal.css';

export default function Signup() {
  const { signup } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: '', phone_number: '', password: '', location: '', accept_terms: false });
  const [error, setError] = useState(''); const [loading, setLoading] = useState(false);
  const update = (key) => (e) => setForm(v => ({ ...v, [key]: e.target.value }));
  const submit = async (e) => {
    e.preventDefault(); setError(''); setLoading(true);
    try {
      const user = await signup(form);
      navigate(dashboardPath(user), { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };
  return <div className="auth-page"><div className="auth-card">
    <div className="brand-mark">C</div><p className="eyebrow">Join CONNECT</p><h1>Create your account</h1><p className="muted">Book rides quickly and keep every trip in one place.</p>
    {error && <div className="error">{error}</div>}
    <form onSubmit={submit} className="form-stack">
      <label>First and last name<input className="input" value={form.name} onChange={update('name')} placeholder="e.g. Collins Otieno" autoComplete="name" maxLength="150" pattern=" *[A-Za-z\u00C0-\u024F'’\-]{2,}( +[A-Za-z\u00C0-\u024F'’\-]{2,})+ *" title="Enter your first and last name, e.g. Collins Otieno" required /></label>
      <label>Phone number<input className="input" type="tel" value={form.phone_number} onChange={update('phone_number')} placeholder="07XX XXX XXX or +2547XX XXX XXX" autoComplete="tel" required /></label>
      <label>Usual location<input className="input" value={form.location} onChange={update('location')} placeholder="e.g. CBD" /></label>
      <label>Password<PasswordInput className="input" autoComplete="new-password" minLength="8" value={form.password} onChange={update('password')} required /></label>
      <label className="terms-check">
        <input type="checkbox" checked={form.accept_terms} required
          onChange={(e) => setForm((v) => ({ ...v, accept_terms: e.target.checked }))} />
        <span>
          I am 18 or older and I agree to the <Link to="/legal/terms" target="_blank">Terms of Service</Link>,
          the <Link to="/legal/refunds" target="_blank">Refund Policy</Link> and
          the <Link to="/legal/privacy" target="_blank">Privacy Policy</Link>.
        </span>
      </label>
      <button className="btn btn-primary btn-full" disabled={loading || !form.accept_terms}>{loading ? 'Creating…' : 'Create account'}</button>
    </form>
    <p className="auth-footer">Already registered? <Link to="/login">Sign in</Link></p>
  </div></div>;
}
