import { Canvas } from '@react-three/fiber';
import {
  Component,
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { useThree } from '@react-three/fiber';
import { createPortal } from 'react-dom';

const log = (...args) => console.info('[Vehicle3D]', ...args);
const DEBUG =
  typeof window !== 'undefined' && window.location.search.includes('debug3d=1');

class Boundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    console.error('[Vehicle3D] canvas crashed:', error);
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}

function AimVehicleCamera() {
  const camera = useThree((state) => state.camera);

  useLayoutEffect(() => {
    camera.position.set(55, -80, 70);
    camera.up.set(0, 0, 1);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld(true);
  }, [camera]);

  return null;
}

function VehicleModel({ heading, stale, onReady }) {
  const ready = useRef(false);
  const bodyColor = stale ? '#d84343' : '#f28c28';
  const handleAfterRender = useCallback(() => {
    if (ready.current) return;
    ready.current = true;
    log('first frame rendered');
    onReady?.();
  }, [onReady]);

  return (
    <group rotation={[0, 0, -(heading * Math.PI) / 180]}>
      <mesh position={[0, 0, -0.2]} receiveShadow>
        <circleGeometry args={[2.3, 32]} />
        <meshBasicMaterial color={stale ? '#d84343' : '#102a43'} transparent opacity={0.28} />
      </mesh>
      <mesh position={[0, 0, 0.38]} castShadow>
        <boxGeometry args={[1.95, 4.1, 0.42]} />
        <meshStandardMaterial color="#202b36" roughness={0.7} />
      </mesh>
      <mesh position={[0, 0, 1.65]} castShadow onAfterRender={handleAfterRender}>
        <boxGeometry args={[1.95, 4.2, 2.2]} />
        <meshStandardMaterial
          color={bodyColor}
          roughness={0.42}
          metalness={0.12}
        />
      </mesh>
      <mesh position={[0, 0, 2.79]} castShadow>
        <boxGeometry args={[1.82, 4.02, 0.12]} />
        <meshStandardMaterial color={stale ? '#c83d3d' : '#ffad45'} roughness={0.5} />
      </mesh>
      <mesh position={[0, -2.12, 2.0]} castShadow>
        <boxGeometry args={[1.45, 0.07, 0.82]} />
        <meshStandardMaterial color="#17324d" roughness={0.28} metalness={0.12} />
      </mesh>
      <mesh position={[0, -2.15, 0.38]} castShadow>
        <boxGeometry args={[1.68, 0.16, 0.28]} />
        <meshStandardMaterial color="#d9e2ec" roughness={0.55} />
      </mesh>
      <mesh position={[0, 2.15, 0.38]} castShadow>
        <boxGeometry args={[1.68, 0.16, 0.28]} />
        <meshStandardMaterial color="#ef476f" emissive="#771c35" emissiveIntensity={0.2} />
      </mesh>
      {[-1, 1].map((side) =>
        (
          <Fragment key={`side-${side}`}>
            {[-1.15, 0, 1.15].map((windowY) => (
              <mesh
                key={`window-${side}-${windowY}`}
                position={[side * 0.99, windowY, 2.05]}
                castShadow
              >
                <boxGeometry args={[0.07, 0.82, 0.58]} />
                <meshStandardMaterial color="#17324d" roughness={0.28} metalness={0.12} />
              </mesh>
            ))}
            {[-1, 1].map((axle) => (
              <mesh
                key={`wheel-${side}-${axle}`}
                position={[side * 1.06, axle * 1.28, 0.42]}
                castShadow
              >
                <boxGeometry args={[0.42, 0.82, 0.72]} />
                <meshStandardMaterial color="#18212b" roughness={0.8} />
              </mesh>
            ))}
          </Fragment>
        ),
      )}
    </group>
  );
}

function VehicleScene({ heading, stale, onReady }) {
  return (
    <>
      <AimVehicleCamera />
      <ambientLight intensity={1.1} />
      <directionalLight position={[-30, -40, 70]} intensity={2.2} />
      <group position={[0, 0, 0]} scale={10}>
        <VehicleModel heading={heading} stale={stale} onReady={onReady} />
      </group>
    </>
  );
}

export default function Vehicle3D({
  map,
  latitude,
  longitude,
  position: snappedPosition,
  heading,
  stale = false,
  onReady,
}) {
  const [position, setPosition] = useState(null);
  const anchorRef = useRef(null);
  const lat = Number(latitude);
  const lng = Number(longitude);
  const direction = Number(heading);
  const vehicleHeading = Number.isFinite(direction) ? direction : 0;

  const mapContainer = map?.getContainer?.() ?? null;
  const tiltViewport = mapContainer?.closest('.tilt-stage')?.parentElement ?? null;
  const overlay = tiltViewport || mapContainer;
  const tilted = !!tiltViewport;

  const measure = useCallback(() => {
    const anchor = anchorRef.current;
    if (!anchor || !overlay || !map) return;
    if (!tilted) {
      const position = snappedPosition;
      const point =
        position?.length === 2 &&
        Number.isFinite(position[0]) &&
        Number.isFinite(position[1])
          ? map.latLngToContainerPoint(position)
          : Number.isFinite(lat) && Number.isFinite(lng)
            ? map.latLngToContainerPoint([lat, lng])
            : null;
      if (!point) return;
      anchor.style.left = `${point.x}px`;
      anchor.style.top = `${point.y}px`;
    }
    const anchorBounds = anchor.getBoundingClientRect();
    const overlayBounds = overlay.getBoundingClientRect();
    const x = anchorBounds.left - overlayBounds.left;
    const y = anchorBounds.top - overlayBounds.top;
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    setPosition((previous) =>
      previous && Math.abs(previous.x - x) < 0.5 && Math.abs(previous.y - y) < 0.5
        ? previous
        : { x, y },
    );
  }, [map, overlay, tilted, lat, lng, snappedPosition]);

  useEffect(() => {
    if (!map || !overlay) return undefined;
    log('mounted', { tilted, hasAnchor: !!anchorRef.current });
    measure();
    const animationFrame = requestAnimationFrame(measure);
    const timeout = setTimeout(measure, 400);
    const resizeObserver =
      typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    resizeObserver?.observe(overlay);
    map.on('move zoom resize viewreset', measure);
    window.addEventListener('resize', measure);
    return () => {
      cancelAnimationFrame(animationFrame);
      clearTimeout(timeout);
      resizeObserver?.disconnect();
      map.off('move zoom resize viewreset', measure);
      window.removeEventListener('resize', measure);
    };
  }, [map, overlay, measure, tilted]);

  if (!map || !mapContainer || !overlay) return null;

  const anchorStyle = {
    position: 'absolute',
    width: 0,
    height: 0,
    pointerEvents: 'none',
    ...(tilted ? { left: '50%', top: '50%' } : { left: 0, top: 0 }),
  };

  return (
    <>
      {createPortal(<div ref={anchorRef} aria-hidden="true" style={anchorStyle} />, mapContainer)}
      {position &&
        createPortal(
          <Boundary>
            <Canvas
              orthographic
              camera={{
                position: [55, -80, 70],
                up: [0, 0, 1],
                zoom: 2.3,
                near: 0.1,
                far: 300,
              }}
              dpr={[1, 2]}
              gl={{ alpha: true, antialias: true }}
              onCreated={() => log('canvas created at', position)}
              style={{
                position: 'absolute',
                left: position.x - 130,
                top: position.y - 130,
                width: 260,
                height: 260,
                zIndex: 650,
                pointerEvents: 'none',
                outline: DEBUG ? '2px dashed red' : 'none',
              }}
            >
              <VehicleScene
                heading={tilted ? 0 : vehicleHeading}
                stale={stale}
                onReady={onReady}
              />
            </Canvas>
          </Boundary>,
          overlay,
        )}
    </>
  );
}
