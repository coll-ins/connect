import { lazy, Suspense } from 'react';
import { Link } from 'react-router-dom';
import { webglOk } from '../../components/maps/webgl';
import matatuPhoto from '../../assets/journeys/bookabus.jpeg';

const HeroBus3D = lazy(() => import('./HeroBus3D'));

// First screen of the installed app: one thing to do, then sign in.
export default function Welcome() {
  return (
    <main className="wl">
      <div className="wl-brand"><span className="brand-mark">C</span>CONNECT</div>
      <div className="wl-visual">
        {webglOk
          ? <Suspense fallback={null}><HeroBus3D autoplay frame="center" /></Suspense>
          : <img src={matatuPhoto} alt="A red and white Nairobi matatu at a stage" />}
      </div>
      <div className="wl-copy">
        <h1>Your matatu seat, booked before you reach the stage.</h1>
        <p>Pick your seat, pay with M-Pesa or card, and watch the bus come to you.</p>
        <Link to="/login" className="btn btn-primary wl-start">Get started</Link>
        <p className="wl-legal">
          By continuing you agree to the <Link to="/legal/terms">Terms</Link> and <Link to="/legal/privacy">Privacy Policy</Link>.
        </p>
      </div>
    </main>
  );
}
