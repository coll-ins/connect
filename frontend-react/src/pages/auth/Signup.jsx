import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import PasswordInput from '../../components/PasswordInput';
import { dashboardPath } from '../../utils/roleRoutes';
import { firstInvalidField } from '../../utils/formErrors';
import '../../styles/forms.css';

const FIELDS = ['name', 'phone_number', 'location', 'password'];

export default function Signup() {
  const { signup } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: '', phone_number: '', password: '', location: '' });
  const [error, setError] = useState(''); const [loading, setLoading] = useState(false);
  const [invalid, setInvalid] = useState(null);
  const update = (key) => (e) => setForm(v => ({ ...v, [key]: e.target.value }));
  const fieldProps = (key) => ({
    id: `signup-${key}`,
    'aria-invalid': invalid === key ? 'true' : undefined,
    'aria-describedby': invalid === key ? 'signup-error' : undefined,
  });

  useEffect(() => { document.title = 'Create account | CONNECT'; }, []);

  const submit = async (e) => {
    e.preventDefault(); setError(''); setInvalid(null); setLoading(true);
    try {
      const user = await signup(form);
      navigate(dashboardPath(user), { replace: true });
    } catch (err) {
      setError(err.message);
      const field = firstInvalidField(err.data, FIELDS);
      setInvalid(field);
      if (field) document.getElementById(`signup-${field}`)?.focus();
    } finally {
      setLoading(false);
    }
  };
  return <main className="auth-page"><div className="auth-card">
    <div className="brand-mark">C</div><p className="eyebrow">Join CONNECT</p><h1>Create your account</h1><p className="muted">Book rides quickly and keep every trip in one place.</p>
    {error && <div id="signup-error" className="error" role="alert">{error}</div>}
    <form onSubmit={submit} className="form-stack">
      <label>First and last name<input {...fieldProps('name')} className="input" value={form.name} onChange={update('name')} placeholder="e.g. Collins Otieno" autoComplete="name" maxLength="150" pattern=" *[A-Za-zÀ-ɏ'’\-]{2,}( +[A-Za-zÀ-ɏ'’\-]{2,})+ *" title="Enter your first and last name, e.g. Collins Otieno" required /></label>
      <label>Phone number<input {...fieldProps('phone_number')} className="input" type="tel" value={form.phone_number} onChange={update('phone_number')} placeholder="07XX XXX XXX or +2547XX XXX XXX" autoComplete="tel" required /></label>
      <label>Usual location<input {...fieldProps('location')} className="input" value={form.location} onChange={update('location')} placeholder="e.g. CBD" /></label>
      <div className="form-field"><label htmlFor="signup-password">Password</label><PasswordInput {...fieldProps('password')} className="input" autoComplete="new-password" minLength="8" value={form.password} onChange={update('password')} required /></div>
      <button className="btn btn-primary btn-full" disabled={loading}>{loading ? 'Creating…' : 'Create account'}</button>
    </form>
    <p className="auth-footer">Already registered? <Link to="/login">Sign in</Link></p>
  </div></main>;
}
