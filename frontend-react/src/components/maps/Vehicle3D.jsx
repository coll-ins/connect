import { Canvas, extend } from '@react-three/fiber';
import { PMREMGenerator } from 'three';
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import {
  Component,
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useThree } from '@react-three/fiber';
import { createPortal } from 'react-dom';

extend({ RoundedBoxGeometry });

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

// Camera sits due south of the bus so map north stays screen-up and headings line up.
const CAMERA_POSITION = [0, -90, 78];

function AimVehicleCamera() {
  const camera = useThree((state) => state.camera);

  useLayoutEffect(() => {
    camera.position.set(...CAMERA_POSITION);
    camera.up.set(0, 0, 1);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld(true);
  }, [camera]);

  return null;
}

// Soft studio reflections so paint, glass and rims read as real materials.
function StudioEnvironment() {
  const gl = useThree((state) => state.gl);
  const texture = useMemo(() => {
    const pmrem = new PMREMGenerator(gl);
    const result = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    pmrem.dispose();
    return result;
  }, [gl]);

  useEffect(() => () => texture.dispose(), [texture]);

  return <primitive object={texture} attach="environment" />;
}

// Bus dimensions in model units: x = width, y = length (front is +y), z = up.
const W = 1.6;
const L = 4.7;
const FRONT = L / 2;
const PILLARS = [-1.95, -1.33, -0.71, -0.09, 0.53];
const AXLES = [1.45, -1.3];

function Wheel({ x, y }) {
  return (
    <group position={[x, y, 0.36]} rotation={[0, 0, Math.PI / 2]}>
      <mesh castShadow>
        <cylinderGeometry args={[0.36, 0.36, 0.3, 28]} />
        <meshStandardMaterial color="#15191e" roughness={0.92} />
      </mesh>
      <mesh>
        <cylinderGeometry args={[0.21, 0.21, 0.31, 24]} />
        <meshStandardMaterial color="#c9ced6" metalness={0.85} roughness={0.28} />
      </mesh>
      <mesh>
        <cylinderGeometry args={[0.07, 0.07, 0.33, 12]} />
        <meshStandardMaterial color="#3a4048" metalness={0.6} roughness={0.4} />
      </mesh>
    </group>
  );
}

function VehicleModel({ heading, stale, onReady }) {
  const ready = useRef(false);
  const livery = stale ? '#d84343' : '#f28c28';
  const handleAfterRender = useCallback(() => {
    if (ready.current) return;
    ready.current = true;
    log('first frame rendered');
    onReady?.();
  }, [onReady]);

  const paint = (
    <meshPhysicalMaterial color="#f5f3ee" roughness={0.32} clearcoat={0.7} clearcoatRoughness={0.18} />
  );
  const glass = (
    <meshPhysicalMaterial color="#0c1825" roughness={0.06} metalness={0.25} clearcoat={1} />
  );

  return (
    <group rotation={[0, 0, -(heading * Math.PI) / 180]}>
      <mesh position={[0, 0, 0.01]} scale={[W * 0.72, L * 0.56, 1]}>
        <circleGeometry args={[1, 40]} />
        <meshBasicMaterial color="#000000" transparent opacity={0.3} depthWrite={false} />
      </mesh>

      <mesh position={[0, 0, 0.3]}>
        <boxGeometry args={[W - 0.12, L - 0.4, 0.22]} />
        <meshStandardMaterial color="#1b2128" roughness={0.9} />
      </mesh>

      {/* Body shell, lower livery skirt and waist stripe */}
      <mesh position={[0, 0, 1.14]} castShadow onAfterRender={handleAfterRender}>
        <roundedBoxGeometry args={[W, L, 1.62, 4, 0.2]} />
        {paint}
      </mesh>
      <mesh position={[0, 0, 0.56]}>
        <roundedBoxGeometry args={[W + 0.02, L + 0.02, 0.42, 3, 0.12]} />
        <meshPhysicalMaterial color={livery} roughness={0.35} clearcoat={0.6} />
      </mesh>
      <mesh position={[0, 0, 1.03]}>
        <roundedBoxGeometry args={[W + 0.02, L + 0.02, 0.07, 2, 0.03]} />
        <meshStandardMaterial color={livery} roughness={0.4} />
      </mesh>

      {/* Wrap-around tinted glass, split by body-coloured pillars */}
      <mesh position={[0, -0.05, 1.43]}>
        <roundedBoxGeometry args={[W + 0.016, L - 0.1, 0.52, 3, 0.08]} />
        {glass}
      </mesh>
      {[-1, 1].map((side) =>
        PILLARS.map((y) => (
          <mesh key={`pillar-${side}-${y}`} position={[side * (W / 2 + 0.012), y, 1.43]}>
            <boxGeometry args={[0.03, 0.07, 0.54]} />
            {paint}
          </mesh>
        )),
      )}
      <mesh position={[0, FRONT + 0.01, 1.36]}>
        <boxGeometry args={[W - 0.16, 0.03, 0.8]} />
        {glass}
      </mesh>
      <mesh position={[-(W / 2 + 0.013), FRONT - 0.58, 1.06]}>
        <boxGeometry args={[0.02, 0.6, 1.16]} />
        {glass}
      </mesh>

      {/* Roof, AC unit and hatch */}
      <mesh position={[0, -0.05, 1.98]}>
        <roundedBoxGeometry args={[W - 0.14, L - 0.35, 0.1, 2, 0.05]} />
        <meshStandardMaterial color="#e6e3dc" roughness={0.5} />
      </mesh>
      <mesh position={[0, -0.45, 2.1]} castShadow>
        <roundedBoxGeometry args={[0.95, 1.15, 0.18, 3, 0.07]} />
        <meshStandardMaterial color="#d3d8de" roughness={0.45} metalness={0.2} />
      </mesh>
      <mesh position={[0, 1.15, 2.05]}>
        <boxGeometry args={[0.55, 0.5, 0.06]} />
        <meshStandardMaterial color="#9aa3ad" roughness={0.5} />
      </mesh>

      {/* Front: destination sign, grille, lamps, bumper, mirrors */}
      <mesh position={[0, FRONT + 0.012, 1.86]}>
        <boxGeometry args={[W - 0.5, 0.03, 0.15]} />
        <meshStandardMaterial color="#1a1206" emissive="#ffb020" emissiveIntensity={0.9} />
      </mesh>
      <mesh position={[0, FRONT + 0.015, 0.64]}>
        <boxGeometry args={[W - 0.62, 0.03, 0.22]} />
        <meshStandardMaterial color="#20262d" roughness={0.6} metalness={0.3} />
      </mesh>
      {[-1, 1].map((side) => (
        <Fragment key={`front-${side}`}>
          <mesh position={[side * 0.56, FRONT + 0.018, 0.66]}>
            <boxGeometry args={[0.26, 0.03, 0.13]} />
            <meshStandardMaterial color="#fffaf0" emissive="#fff3cf" emissiveIntensity={1.1} />
          </mesh>
          <mesh position={[side * 0.71, FRONT + 0.018, 0.52]}>
            <boxGeometry args={[0.1, 0.03, 0.07]} />
            <meshStandardMaterial color="#ffb347" emissive="#ff9a1f" emissiveIntensity={0.7} />
          </mesh>
          <mesh position={[side * (W / 2 + 0.09), FRONT - 0.05, 1.56]}>
            <boxGeometry args={[0.18, 0.03, 0.03]} />
            <meshStandardMaterial color="#14181d" />
          </mesh>
          <mesh position={[side * (W / 2 + 0.18), FRONT - 0.02, 1.42]}>
            <boxGeometry args={[0.05, 0.09, 0.28]} />
            <meshStandardMaterial color="#14181d" roughness={0.4} />
          </mesh>
          <mesh position={[side * 0.68, -FRONT - 0.012, 0.74]}>
            <boxGeometry args={[0.13, 0.03, 0.38]} />
            <meshStandardMaterial color="#8a0f1c" emissive="#e0203a" emissiveIntensity={0.8} />
          </mesh>
        </Fragment>
      ))}
      <mesh position={[0, FRONT + 0.04, 0.4]}>
        <roundedBoxGeometry args={[W + 0.04, 0.16, 0.18, 2, 0.06]} />
        <meshStandardMaterial color="#2a3038" roughness={0.55} />
      </mesh>
      <mesh position={[0, -FRONT - 0.04, 0.4]}>
        <roundedBoxGeometry args={[W + 0.04, 0.16, 0.18, 2, 0.06]} />
        <meshStandardMaterial color="#2a3038" roughness={0.55} />
      </mesh>

      {/* Wheel arches and wheels */}
      {[-1, 1].map((side) =>
        AXLES.map((y) => (
          <Fragment key={`wheel-${side}-${y}`}>
            <mesh position={[side * (W / 2 + 0.008), y, 0.4]} rotation={[0, 0, Math.PI / 2]}>
              <cylinderGeometry args={[0.43, 0.43, 0.02, 28]} />
              <meshStandardMaterial color="#0e1115" roughness={1} />
            </mesh>
            <Wheel x={side * (W / 2 - 0.12)} y={y} />
          </Fragment>
        )),
      )}
    </group>
  );
}

function VehicleScene({ heading, stale, onReady }) {
  return (
    <>
      <AimVehicleCamera />
      <StudioEnvironment />
      <hemisphereLight args={['#ffffff', '#5b6470', 0.7]} />
      <directionalLight position={[-35, -50, 90]} intensity={1.9} />
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
              frameloop="demand"
              camera={{
                position: CAMERA_POSITION,
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
