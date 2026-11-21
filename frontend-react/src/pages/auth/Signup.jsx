import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import PasswordInput from '../../components/PasswordInput';
import PasswordChecklist, { passwordIsStrong } from '../../components/PasswordChecklist';
import { dashboardPath } from '../../utils/roleRoutes';
import FieldNote from '../../components/FieldNote';
import { checkName, checkPhone, checkPlace, PHONE_HINT } from '../../utils/inputRules';
import { firstInvalidField } from '../../utils/formErrors';
import '../../legal/Legal.css';
import './Auth.css';
import '../../styles/forms.css';
import AuthTopBar from './AuthTopBar';

// One name part: letters (incl. accented), apostrophes, hyphens; 2+ characters.
const NAME_PATTERN = " *[A-Za-z\\u00C0-\\u024F'’\\-]{2,} *";
// Server error keys, in form order. The server reports the two name inputs as one `name`.
const FIELDS = ['name', 'phone_number', 'location', 'password'];
const FOCUS_ID = { name: 'first_name' };

export default function Signup() {
  const { signup } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    first_name: '', last_name: '', phone_number: '', password: '', location: '', accept_terms: false,
  });
  const [error, setError] = useState(''); const [loading, setLoading] = useState(false);
  const [pwTouched, setPwTouched] = useState(false);
  const [invalid, setInvalid] = useState(null);
  const update = (key) => (e) => setForm(v => ({ ...v, [key]: e.target.value }));
  const strong = passwordIsStrong(form.password);
  const fullName = `${form.first_name} ${form.last_name}`;
  const errName = form.first_name.trim() && form.last_name.trim() ? checkName(fullName, 'your name') : '';
  const errPhone = checkPhone(form.phone_number);
  const errLocation = checkPlace(form.location, 'your usual location', { required: false, example: 'e.g. CBD or Rongai' });
  // Ties an input to the alert (after a failed submit) and to its own hint, so a screen reader hears both.
  const fieldProps = (key, note) => ({
    id: `signup-${key}`,
    'aria-describedby': [invalid === key ? 'signup-error' : '', note].filter(Boolean).join(' ') || undefined,
  });

  useEffect(() => { document.title = 'Create account | CONNECT'; }, []);

  const submit = async (e) => {
    e.preventDefault(); if (loading) return; setError(''); setInvalid(null);
    const problem = errName || errPhone || errLocation;
    if (problem) {
      setError(problem);
      const key = errName ? 'first_name' : errPhone ? 'phone_number' : 'location';
      setInvalid(key); document.getElementById(`signup-${key}`)?.focus();
      return;
    }
    if (!strong) { setPwTouched(true); setInvalid('password'); setError('Your password does not meet every requirement below.'); document.getElementById('signup-password')?.focus(); return; }
    setLoading(true);
    try {
      const { first_name, last_name, ...rest } = form;
      const user = await signup({ ...rest, name: `${first_name.trim()} ${last_name.trim()}` });
      navigate(dashboardPath(user), { replace: true });
    } catch (err) {
      setError(err.message);
      const field = firstInvalidField(err.data, FIELDS);
      const key = FOCUS_ID[field] || field;
      setInvalid(key);
      if (key) document.getElementById(`signup-${key}`)?.focus();
    } finally {
      setLoading(false);
    }
  };

  return <main className="auth-page"><div className="auth-card">
    <AuthTopBar mode="signup" />
    <h1>Create your account</h1>
    <p className="muted">Book matatu seats, track your bus live and keep every receipt in one place.</p>
    {error && <div id="signup-error" className="error" role="alert">{error}</div>}
    <form onSubmit={submit} className="form-stack">
      <div className="name-row">
        <label>First name
          <input {...fieldProps('first_name', 'su-name')} className="input" value={form.first_name} onChange={update('first_name')} autoComplete="given-name"
            maxLength="70" pattern={NAME_PATTERN} title="At least 2 letters, e.g. Collins"
            aria-invalid={invalid === 'first_name' || undefined} required />
        </label>
        <label>Last name
          <input id="signup-last_name" className="input" value={form.last_name} onChange={update('last_name')} autoComplete="family-name"
            aria-describedby="su-name" maxLength="70" pattern={NAME_PATTERN} title="At least 2 letters, e.g. Otieno" required />
        </label>
      </div>
      <FieldNote id="su-name" value={errName ? fullName : ''} error={errName}
        hint="Your real first and last name, as on your ID. Drivers use it to check your ticket." />
      <label>Phone number<input {...fieldProps('phone_number', 'su-phone')} className="input" type="tel" inputMode="tel" maxLength={16} value={form.phone_number} onChange={update('phone_number')}
        placeholder="07XX XXX XXX" autoComplete="tel" required
        aria-invalid={invalid === 'phone_number' || Boolean(form.phone_number.trim() && errPhone) || undefined} /></label>
      <FieldNote id="su-phone" value={form.phone_number} error={errPhone}
        hint={`You sign in with it and pay with M-PESA on it. ${PHONE_HINT}`} />
      <label><span>Usual location <span className="label-optional">(optional)</span></span><input {...fieldProps('location', 'su-loc')} className="input" value={form.location} onChange={update('location')}
        placeholder="e.g. CBD" maxLength={100}
        aria-invalid={invalid === 'location' || Boolean(form.location.trim() && errLocation) || undefined} /></label>
      <FieldNote id="su-loc" value={form.location} error={errLocation}
        hint="The area you usually travel from, so we show your stage first." />
      <div className="form-field"><label htmlFor="signup-password">Password</label>
        <PasswordInput {...fieldProps('password', 'pw-rules')} className={`input${pwTouched && !strong ? ' input-invalid' : ''}`} autoComplete="new-password"
          value={form.password} onChange={update('password')}
          aria-invalid={invalid === 'password' || (pwTouched && !strong) || undefined} required />
      </div>
      <PasswordChecklist id="pw-rules" password={form.password} />
      <label className="terms-check">
        <input type="checkbox" checked={form.accept_terms} required
          onChange={(e) => setForm((v) => ({ ...v, accept_terms: e.target.checked }))} />
        <span>
          I am 18 or older and I agree to the <Link to="/legal/terms" target="_blank">Terms of Service</Link>,
          the <Link to="/legal/refunds" target="_blank">Refund Policy</Link> and
          the <Link to="/legal/privacy" target="_blank">Privacy Policy</Link>.
        </span>
      </label>
      <button className="btn btn-primary btn-full" disabled={loading || !form.accept_terms}>{loading ? 'Creating account…' : 'Create account'}</button>
    </form>
  </div></main>;
}
