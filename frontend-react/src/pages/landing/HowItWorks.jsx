import { useState } from 'react';
import { SERVICES } from './howItWorks';

// Website: one route line of steps, switched between the three services.
export default function HowItWorks() {
  const [active, setActive] = useState(SERVICES[0].id);
  const service = SERVICES.find((s) => s.id === active);

  return (
    <section className="lp-section lp-wrap" aria-labelledby="lp-how">
      <h2 id="lp-how">How it works</h2>
      <div className="lp-how-tabs" role="tablist" aria-label="Services">
        {SERVICES.map(({ id, icon: Icon, name }) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`lp-how-tab-${id}`}
            aria-selected={id === active}
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
