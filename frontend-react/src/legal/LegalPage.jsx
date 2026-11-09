import { useEffect } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import { ChevronLeft } from 'lucide-react';

import { LAST_UPDATED } from './business';
import { DOCUMENTS, documentBySlug } from './documents';
import './Legal.css';

function Block({ item }) {
  if (typeof item === 'string') return <p>{item}</p>;
  if (item.list) {
    return <ul>{item.list.map((li) => <li key={li}>{li}</li>)}</ul>;
  }
  const [head, ...rows] = item.table;
  return (
    <div className="legal-table-wrap">
      <table className={`legal-table${head.length > 2 ? ' is-wide' : ''}`}>
        <thead><tr>{head.map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
        <tbody>
          {rows.map((r) => <tr key={r[0]}>{r.map((c) => <td key={c}>{c}</td>)}</tr>)}
        </tbody>
      </table>
    </div>
  );
}

export default function LegalPage() {
  const { slug } = useParams();
  const doc = documentBySlug(slug);
  const navigate = useNavigate();

  useEffect(() => {
    if (doc) document.title = `${doc.title} · CONNECT`;
    window.scrollTo(0, 0);
  }, [doc]);

  if (!doc) return <Navigate to="/legal/terms" replace />;

  return (
    <div className="legal-page">
      <header className="legal-top">
        <Link to="/" className="legal-brand"><span className="brand-mark" aria-hidden="true">C</span>CONNECT</Link>
        <nav aria-label="Legal documents" className="legal-nav">
          {DOCUMENTS.map((d) => (
            <Link key={d.slug} to={`/legal/${d.slug}`}
              className={d.slug === slug ? 'is-active' : undefined}
              aria-current={d.slug === slug ? 'page' : undefined}>
              {d.title}
            </Link>
          ))}
        </nav>
      </header>

      <main className="legal-doc">
        <button
          type="button"
          className="journey-back"
          // Opened from a link inside the app: go back there. Opened directly: go home.
          onClick={() => (window.history.state?.idx > 0 ? navigate(-1) : navigate('/', { replace: true }))}
        >
          <ChevronLeft size={20} aria-hidden="true" /> Back
        </button>
        <h1>{doc.title}</h1>
        <p className="legal-meta">Last updated {LAST_UPDATED}</p>
        <p className="legal-summary">{doc.summary}</p>
        {doc.sections.map((s) => (
          <section key={s.h}>
            <h2>{s.h}</h2>
            {s.body.map((item, i) => <Block key={i} item={item} />)}
          </section>
        ))}
      </main>
    </div>
  );
}
