import { lazy, Suspense } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { Armchair, MapPinned, Package, Bus, Receipt, ShieldCheck, Check } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { dashboardPath } from '../../utils/roleRoutes';
import { webglOk } from '../../components/maps/webgl';
import matatuPhoto from '../../assets/journeys/bookabus.jpeg';
import seatPhoto from '../../assets/journeys/bookaseat.jpeg';
import './Landing.css';

// three.js is large: fetched after the words and buttons are already on screen.
const HeroBus3D = lazy(() => import('./HeroBus3D'));

const PROBLEMS = [
  {
    pain: 'You reach the stage and the matatu is already full.',
    fix: 'Book your seat before you leave the house. It is held for you until the bus leaves.',
  },
  {
    pain: 'You wait without knowing where the bus is.',
    fix: 'Watch your bus move on a live map, stage by stage, with traffic on the route.',
  },
  {
    pain: 'No change, no receipt.',
    fix: 'Pay with M-Pesa or card and get a receipt for every trip, searchable any time.',
  },
  {
    pain: 'You left something on the bus and nobody to call.',
    fix: 'Your receipt names the driver, the bus and their number once your trip is paid.',
  },
];

const FEATURES = [
  { icon: Armchair, title: 'Pick your exact seat', text: 'See which seats are free on the next trips and choose yours.' },
  { icon: MapPinned, title: 'Live bus tracking', text: 'Know when to walk to your stage instead of guessing.' },
  { icon: Package, title: 'Send parcels', text: 'Send a package with a matatu on your route and follow it to delivery.' },
  { icon: Bus, title: 'Hire a whole bus', text: 'Book a charter for a wedding, a church trip or a school outing.' },
  { icon: Receipt, title: 'Receipts and history', text: 'Every booking, payment and refund, searchable by reference.' },
  { icon: ShieldCheck, title: 'Boarding PIN', text: 'Only you can board on your seat. The driver checks your PIN.' },
];

// The real 14-seater HiAce: 2 beside the driver (front right), then rows of 3.
// Seat 7 matches the hero ticket.
const SEATS = [
  'taken', 'free', 'driver',
  'free', 'taken', 'free',
  'mine', 'taken', 'free',
  'free', 'free', 'taken',
  'taken', 'free', 'free',
];
let seatNo = 0;
const SEAT_LABELS = SEATS.map((state) => (state === 'driver' ? '' : String(++seatNo)));

const STEPS = [
  { title: 'Create your account', text: 'Your name, phone number and a password. Takes a minute.' },
  { title: 'Choose route and seat', text: 'Pick the company, the trip time and the seat you want.' },
  { title: 'Pay', text: 'M-Pesa or card. Your seat is confirmed the moment it is paid.' },
  { title: 'Board with your PIN', text: 'Track the bus, walk to your stage, show your PIN, ride.' },
];

export default function Landing() {
  const { user } = useAuth();
  if (user) return <Navigate to={dashboardPath(user)} replace />;

  return (
    <div className="lp">
      <header className="lp-nav lp-wrap">
        <Link to="/" className="lp-logo"><span className="brand-mark">C</span>CONNECT</Link>
        <nav className="lp-nav-actions">
          <Link to="/login" className="lp-link">Sign in</Link>
          <Link to="/signup" className="btn btn-primary">Get started</Link>
        </nav>
      </header>

      <section className="lp-hero lp-wrap">
        <div className="lp-hero-copy">
          <h1>Your matatu seat, booked before you reach the stage.</h1>
          <p className="lp-lead">
            CONNECT lets you book a seat on a matatu, pay for it, and watch the bus come to you on a live map.
            No pushing at the stage, no waiting blind.
          </p>
          <div className="lp-cta">
            <Link to="/signup" className="btn btn-primary lp-btn-lg">Get started</Link>
            <Link to="/login" className="lp-link">I already have an account</Link>
          </div>
          <p className="lp-fact">Free to join. Pay with M-Pesa or card.</p>
        </div>

        <div className="lp-hero-visual">
          {webglOk ? (
            <div className="lp-stage">
              <Suspense fallback={null}><HeroBus3D /></Suspense>
              <p className="lp-stage-caption">The bus you book, on its way to your stage.</p>
            </div>
          ) : (
            <img src={matatuPhoto} alt="A red and white Nairobi matatu parked at a stage" width="736" height="1308" />
          )}
          <div className="lp-ticket" aria-hidden="true">
            <div className="lp-ticket-row">
              <span>CBD → Rongai</span>
              <span className="lp-live"><i />Live</span>
            </div>
            <div className="lp-ticket-route"><b /><span /><b /></div>
            <dl>
              <div><dt>Seat</dt><dd>7</dd></div>
              <div><dt>Leaves</dt><dd>17:40</dd></div>
              <div><dt>Fare</dt><dd>KES 150</dd></div>
              <div><dt>PIN</dt><dd>4 8 2 1</dd></div>
            </dl>
            <p>Bus is 2 stages away, about 6 min</p>
          </div>
        </div>
      </section>

      <section className="lp-section lp-wrap">
        <h2>What it fixes</h2>
        <ul className="lp-problems">
          {PROBLEMS.map((p) => (
            <li key={p.pain}>
              <p className="lp-pain">{p.pain}</p>
              <p className="lp-fix"><Check size={18} aria-hidden="true" />{p.fix}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="lp-section lp-wrap lp-split">
        <div className="lp-seat-photo">
          <img src={seatPhoto} alt="Reclining bus seats with seat belts" width="736" height="981" loading="lazy" />
          <div className="lp-seatmap" aria-hidden="true">
            <p>Pick a seat</p>
            <div className="lp-seats">
              {SEATS.map((state, i) => <span key={i} className={`lp-seat is-${state}`}>{SEAT_LABELS[i]}</span>)}
            </div>
            <div className="lp-legend"><span className="is-free">Free</span><span className="is-taken">Taken</span><span className="is-mine">Yours</span></div>
          </div>
        </div>
        <div>
          <h2>Everything for the trip, in one app</h2>
          <ul className="lp-features">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <li key={title}>
                <Icon size={20} aria-hidden="true" />
                <div><h3>{title}</h3><p>{text}</p></div>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="lp-section lp-wrap">
        <h2>How it works</h2>
        <ol className="lp-steps">
          {STEPS.map((s) => (
            <li key={s.title}><h3>{s.title}</h3><p>{s.text}</p></li>
          ))}
        </ol>
      </section>

      <section className="lp-section lp-wrap">
        <div className="lp-final">
          <div>
            <h2>Next time, skip the queue at the stage.</h2>
            <p>Create an account in a minute and book your first seat today.</p>
          </div>
          <Link to="/signup" className="btn btn-primary lp-btn-lg">Create your free account</Link>
        </div>
      </section>

      <footer className="lp-footer lp-wrap">
        <span>© {new Date().getFullYear()} CONNECT</span>
        <nav>
          <Link to="/legal/terms">Terms</Link>
          <Link to="/legal/privacy">Privacy</Link>
          <Link to="/legal/refunds">Refunds</Link>
        </nav>
      </footer>
    </div>
  );
}
