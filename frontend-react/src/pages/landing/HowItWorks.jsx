import { useState } from 'react';
import { SERVICES } from './howItWorks';

// Website: one route line of steps, switched between the three services.
export default function HowItWorks() {
  const [active, setActive] = useState(SERVICES[0].id);
  const service = SERVICES.find((s) => s.id === active);
  // Arrow keys, Home and End move between tabs, as in any tab list.
  const onKey = (e) => {
    const i = SERVICES.findIndex((s) => s.id === active);
    const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: SERVICES.length - 1 }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    const next = SERVICES[(to + SERVICES.length) % SERVICES.length].id;
    setActive(next);
    document.getElementById(`lp-how-tab-${next}`)?.focus();
  };

  return (
    <section className="lp-section lp-wrap" aria-labelledby="lp-how">
      <h2 id="lp-how">How it works</h2>
      <div className="lp-how-tabs" role="tablist" aria-label="Services" onKeyDown={onKey}>
        {SERVICES.map(({ id, icon: Icon, name }) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`lp-how-tab-${id}`}
            aria-selected={id === active}
            tabIndex={id === active ? 0 : -1}
            aria-controls="lp-how-panel"
            onClick={() => setActive(id)}
          >
            <Icon size={18} aria-hidden="true" />{name}
          </button>
        ))}
      </div>
      <div id="lp-how-panel" role="tabpanel" aria-labelledby={`lp-how-tab-${active}`}>
        <p className="lp-how-line">{service.line}</p>
        <ol className="lp-steps" key={active}>
          {service.steps.map((s) => (
            <li key={s.title}><h3>{s.title}</h3><p>{s.text}</p></li>
          ))}
        </ol>
      </div>
    </section>
  );
}
