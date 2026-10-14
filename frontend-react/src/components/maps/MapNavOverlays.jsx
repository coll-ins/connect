import { useEffect, useState } from 'react';
import { formatDistance } from './wazeNav';

const glass = {
  background: 'rgba(24, 28, 42, 0.88)',
  color: '#fff',
  border: '1px solid rgba(255,255,255,0.14)',
  backdropFilter: 'blur(10px)',
  WebkitBackdropFilter: 'blur(10px)',
  boxShadow: '0 6px 18px rgba(0,0,0,0.35)',
};

const button = {
  ...glass,
  width: 44,
  height: 44,
  borderRadius: 12,
  fontSize: 24,
  lineHeight: 1,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  cursor: 'pointer',
  padding: 0,
};

const dispatchMapEvent = (name, detail) =>
  window.dispatchEvent(new CustomEvent(name, { detail }));

export function MapZoomButtons({ style }) {
  const [manual, setManual] = useState(false);

  useEffect(() => {
    const onManualChange = (event) => setManual(Boolean(event.detail));
    window.addEventListener('connect-map-manual', onManualChange);
    return () =>
      window.removeEventListener('connect-map-manual', onManualChange);
  }, []);

  return (
    <div
      style={{
        position: 'absolute',
        right: 14,
        top: '38%',
        zIndex: 1200,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        ...style,
      }}
    >
      <button
        type="button"
        aria-label="Zoom in"
        style={button}
        onClick={() => dispatchMapEvent('connect-map-zoom', { delta: 0.75 })}
      >
        +
      </button>
      <button
        type="button"
        aria-label="Zoom out"
        style={button}
        onClick={() => dispatchMapEvent('connect-map-zoom', { delta: -0.75 })}
      >
        −
      </button>
      {manual && (
        <button
          type="button"
          aria-label="Recenter on bus"
          style={{ ...button, background: '#1d6bff', border: 'none' }}
          onClick={() => dispatchMapEvent('connect-map-recenter')}
        >
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#fff"
            strokeWidth="2.2"
            strokeLinecap="round"
          >
            <circle cx="12" cy="12" r="7" />
            <circle cx="12" cy="12" r="2" fill="#fff" />
            <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
          </svg>
        </button>
      )}
    </div>
  );
}

export function NextStageBanner({ next, style }) {
  if (!next) return null;

  return (
    <div
      style={{
        ...glass,
        position: 'absolute',
        top: 14,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 1200,
        borderRadius: 16,
        padding: '10px 16px',
        minWidth: 190,
        maxWidth: '60%',
        textAlign: 'center',
        pointerEvents: 'none',
        ...style,
      }}
    >
      <div
        style={{
          fontSize: 11,
          letterSpacing: 1,
          opacity: 0.7,
          textTransform: 'uppercase',
        }}
      >
        Next stage
      </div>
      <div
        style={{
          fontSize: 17,
          fontWeight: 700,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {next.name}
      </div>
      <div style={{ fontSize: 13, opacity: 0.85 }}>
        {formatDistance(next.distanceM)} · {next.etaMin} min
      </div>
    </div>
  );
}
