import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { webglOk } from '../../components/maps/webgl';
import useHistoryStep from '../../hooks/useHistoryStep';
import matatuPhoto from '../../assets/journeys/bookabus.jpeg';
import { SERVICES } from './howItWorks';

const HeroBus3D = lazy(() => import('./HeroBus3D'));

const STILL = typeof window !== 'undefined'
  && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

// The film: [second, story progress]. The bus cruises, the camera swings to the
// seats, rises over the route, then the bus pulls in and the rider boards.
const FILM = [[0, 0], [3.4, 0.14], [4.6, 0.33], [7.6, 0.43], [8.8, 0.55], [12.6, 0.9], [13.4, 1], [18, 1]];
const LENGTH = FILM[FILM.length - 1][0];
const SCENES = [
  { at: 0, title: 'Your seat, booked before the stage.', text: 'Book a matatu seat in a minute and skip the queue.' },
  { at: 4.2, title: 'Pick the exact seat.', text: 'Window, aisle or front row. Tap the one you want.' },
  { at: 8.4, title: 'Watch it come to you.', text: 'Your bus moves on a live map, stage by stage.' },
  { at: 12.8, title: 'Board with your PIN.', text: 'Show your PIN to the driver and take your seat.' },
];

const smooth = (t) => t * t * (3 - 2 * t);
function filmAt(s) {
  let i = 0;
  while (i < FILM.length - 2 && s > FILM[i + 1][0]) i += 1;
  const [s0, p0] = FILM[i];
  const [s1, p1] = FILM[i + 1];
  return p0 + (p1 - p0) * smooth(Math.min(1, Math.max(0, (s - s0) / (s1 - s0))));
}
const sceneAt = (s) => SCENES.reduce((n, sc, i) => (s >= sc.at ? i : n), 0);

// First screen of the installed app: the street plays like a film behind
// everything, then Get started walks through the three services.
export default function Welcome() {
  const [step, goTo, back] = useHistoryStep();
  const progress = useRef(STILL ? 1 : 0);
  const bars = useRef(null);
  const [scene, setScene] = useState(0);

  useEffect(() => {
    if (STILL) return undefined;
    let frame = 0;
    const start = performance.now();
    const tick = (now) => {
      const s = ((now - start) / 1000) % LENGTH;
      progress.current = filmAt(s);
      const i = sceneAt(s);
      setScene(i);
      const next = i + 1 < SCENES.length ? SCENES[i + 1].at : LENGTH;
      bars.current?.style.setProperty('--fill', ((s - SCENES[i].at) / (next - SCENES[i].at)).toFixed(3));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  const how = step > 0 ? SERVICES[Math.min(step, SERVICES.length) - 1] : null;
  const last = step >= SERVICES.length;

  return (
    <main className={`wl${how ? ' is-how' : ''}`}>
      <div className="wl-film" aria-hidden="true">
        {webglOk
          ? <Suspense fallback={null}><HeroBus3D progress={progress} /></Suspense>
          : <img className="lp-story-photo" src={matatuPhoto} alt="" />}
      </div>
      <div className="wl-scrim" />

      <header className="wl-top">
        {how ? (
          <button type="button" className="wl-back" onClick={back}>
            <ArrowLeft size={20} aria-hidden="true" />Back
          </button>
        ) : (
          <div className="wl-brand"><span className="brand-mark">C</span>CONNECT</div>
        )}
        {how && !last && <Link to="/signup" className="wl-skip">Skip</Link>}
      </header>

      {!how ? (
        <section className="wl-copy">
          {!STILL && (
            <ol className="wl-bars" ref={bars} aria-hidden="true">
              {SCENES.map((_, i) => <li key={i} className={i < scene ? 'is-done' : i === scene ? 'is-now' : ''}><i /></li>)}
            </ol>
          )}
          <div className="wl-scene" key={scene} aria-live="polite">
            <h1>{SCENES[scene].title}</h1>
            <p>{SCENES[scene].text}</p>
          </div>
          <button type="button" className="btn btn-primary wl-start" onClick={() => goTo(1)}>Get started</button>
          <Link to="/login" className="wl-login">I have an account</Link>
          <p className="wl-legal">
            By continuing you agree to the <Link to="/legal/terms">Terms</Link> and <Link to="/legal/privacy">Privacy Policy</Link>.
          </p>
        </section>
      ) : (
        <section className="wl-how" key={how.id} aria-labelledby="wl-how-title">
          <div className="wl-how-icon"><how.icon size={24} aria-hidden="true" /></div>
          <h1 id="wl-how-title">{how.name}</h1>
          <p className="wl-how-line">{how.line}</p>
          <ol className="wl-how-steps">
            {how.steps.map((s) => <li key={s.title}><strong>{s.title}</strong><span>{s.text}</span></li>)}
          </ol>
          <div className="wl-dots" aria-label={`${step} of ${SERVICES.length}`}>
            {SERVICES.map((s, i) => <i key={s.id} className={i + 1 === step ? 'is-on' : ''} />)}
          </div>
          {last ? (
            <>
              <Link to="/signup" className="btn btn-primary wl-start">Create your free account</Link>
              <Link to="/login" className="wl-login">I have an account</Link>
            </>
          ) : (
            <button type="button" className="btn btn-primary wl-start" onClick={() => goTo(step + 1)}>Next</button>
          )}
        </section>
      )}
    </main>
  );
}
