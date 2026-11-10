import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { Armchair, MapPinned, Package, Bus, Receipt, ShieldCheck, Check } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { dashboardPath } from '../../utils/roleRoutes';
import { webglOk } from '../../components/maps/webgl';
import matatuPhoto from '../../assets/journeys/bookabus.jpeg';
import seatPhoto from '../../assets/journeys/bookaseat.jpeg';
import { isInstalledApp } from '../../utils/installedApp';
import Welcome from './Welcome';
import InstallApp from './InstallApp';
import HowItWorks from './HowItWorks';
import './Landing.css';

// three.js is large: fetched after the words and buttons are already on screen.
const HeroBus3D = lazy(() => import('./HeroBus3D'));

const STILL = typeof window !== 'undefined'
  && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

// Scroll position where each chapter takes over (matches the camera stops in HeroBus3D).
const CHAPTER_AT = [0, 0.22, 0.5, 0.8];

function SeatCard() {
  return (
    <div className="lp-seatmap" aria-hidden="true">
      <p>Pick a seat</p>
      <div className="lp-seats">
        {SEATS.map((state, i) => <span key={i} className={`lp-seat is-${state}`}>{SEAT_LABELS[i]}</span>)}
      </div>
      <div className="lp-legend"><span className="is-free">Free</span><span className="is-taken">Taken</span><span className="is-mine">Yours</span></div>
    </div>
  );
}

function Ticket({ arrived }) {
  return (
    <div className="lp-ticket" aria-hidden="true">
      <div className="lp-ticket-row">
        <span>CBD to Rongai</span>
        <span className="lp-live"><i />{arrived ? 'At your stage' : 'Live'}</span>
      </div>
      <div className="lp-ticket-route"><b /><span /><b /></div>
      <dl>
        <div><dt>Seat</dt><dd>6</dd></div>
        <div><dt>Leaves</dt><dd>17:40</dd></div>
        <div><dt>Fare</dt><dd>KES 150</dd></div>
        <div><dt>PIN</dt><dd>4 8 2 1</dd></div>
      </dl>
      <p>{arrived ? 'Show your PIN to the driver and board.' : 'Bus is 2 stages away, about 6 min'}</p>
    </div>
  );
}

// The first screens: the street stays pinned while the words change, and the
// matatu drives up to the stage as the visitor scrolls.
function Story() {
  const section = useRef(null);
  const progress = useRef(0);
  const [chapter, setChapter] = useState(0);

  useEffect(() => {
    const el = section.current;
    if (!el || STILL) return undefined;
    let frame = 0;
    const read = () => {
      frame = 0;
      const r = el.getBoundingClientRect();
      // The pinned stage's own height (100svh), not innerHeight, which
      // changes as a phone's address bar slides away.
      const pinned = el.firstElementChild.offsetHeight;
      const p = Math.min(1, Math.max(0, -r.top / Math.max(1, r.height - pinned)));
      progress.current = p;
      el.style.setProperty('--p', p.toFixed(4));
      let c = 0;
      while (c < CHAPTER_AT.length - 1 && p >= CHAPTER_AT[c + 1]) c += 1;
      setChapter(c);
    };
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(read); };
    read();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  }, []);

  // Every chapter stays in the reading order for screen readers. Tabbing into
  // one that is not showing scrolls the story to it, so focus is never invisible.
  const at = (i) => ({
    className: `lp-chapter${STILL || chapter === i ? ' is-on' : ''}`,
    onFocus: () => {
      const el = section.current;
      if (STILL || !el || chapter === i) return;
      const span = el.offsetHeight - el.firstElementChild.offsetHeight;
      const top = el.getBoundingClientRect().top + window.scrollY;
      window.scrollTo({ top: top + span * (CHAPTER_AT[i] + 0.04) });
    },
  });

  return (
    <section ref={section} className={`lp-story${STILL ? ' is-still' : ''}`}>
      <div className="lp-story-stage">
        {webglOk ? (
          <Suspense fallback={null}><HeroBus3D progress={progress} /></Suspense>
        ) : (
          <img className="lp-story-photo" src={matatuPhoto} alt="A red and white Nairobi matatu parked at a stage" />
        )}
        <div className="lp-story-scrim" />
        {!STILL && (
          <ol className="lp-story-route" aria-hidden="true">
            {CHAPTER_AT.map((_, i) => <li key={i} className={i <= chapter ? 'is-done' : ''} />)}
          </ol>
        )}

      <div className="lp-chapters lp-wrap">
        <div {...at(0)}>
          <h1>Your matatu seat, booked before you reach the stage.</h1>
          <p className="lp-lead">
            Book a seat on a matatu, pay for it, and watch the bus come to you on a live map.
            No pushing at the stage, no waiting blind.
          </p>
          <div className="lp-cta">
            <Link to="/signup" className="btn btn-primary lp-btn-lg">Get started</Link>
            <Link to="/login" className="lp-link">I have an account</Link>
          </div>
          <p className="lp-fact">Free to join. Pay with M-Pesa or card.</p>
          <InstallApp />
          {!STILL && <p className="lp-scroll-cue" aria-hidden="true">Scroll to ride along</p>}
        </div>

        <div {...at(1)}>
          <h2>Pick the exact seat.</h2>
          <p className="lp-lead">See which seats are free on the next trips and tap the one you want. Window, aisle, front row. It is yours once it is paid.</p>
          <SeatCard />
        </div>

        <div {...at(2)}>
          <h2>Watch it come to you.</h2>
          <p className="lp-lead">Your bus moves on a live map, stage by stage. Leave the house when it is close, not an hour early.</p>
          <Ticket />
        </div>

        <div {...at(3)}>
          <h2>Board with your PIN.</h2>
          <p className="lp-lead">The driver checks your PIN, you take your seat. Your receipt names the bus, the driver and the fare.</p>
          <Ticket arrived />
          <div className="lp-cta">
            <Link to="/signup" className="btn btn-primary lp-btn-lg">Book your first seat</Link>
          </div>
        </div>
      </div>
      </div>
    </section>
  );
}

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
// Seat 6 matches the ticket in the story.
const SEATS = [
  'taken', 'free', 'driver',
  'free', 'taken', 'free',
  'mine', 'taken', 'free',
  'free', 'free', 'taken',
  'taken', 'free', 'free',
];
let seatNo = 0;
const SEAT_LABELS = SEATS.map((state) => (state === 'driver' ? '' : String(++seatNo)));

export default function Landing() {
  const { user } = useAuth();
  if (user) return <Navigate to={dashboardPath(user)} replace />;
  if (isInstalledApp()) return <Welcome />;

  return (
    <div className="lp">
      <header className="lp-nav">
        <div className="lp-nav-in lp-wrap">
        <Link to="/" className="lp-logo"><span className="brand-mark">C</span>CONNECT</Link>
        <nav className="lp-nav-actions">
          <Link to="/login" className="lp-link">Log in</Link>
          <Link to="/signup" className="btn btn-primary">Get started</Link>
        </nav>
        </div>
      </header>

      <Story />

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

      <HowItWorks />

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
