import { formatDistance } from './wazeNav';

const glass = {
  background: 'rgba(24, 28, 42, 0.88)',
  color: '#fff',
  border: '1px solid rgba(255,255,255,0.14)',
  backdropFilter: 'blur(10px)',
  WebkitBackdropFilter: 'blur(10px)',
  boxShadow: '0 6px 18px rgba(0,0,0,0.35)',
};

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
          opacity: 0.7,
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
