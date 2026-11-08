import { Canvas, extend, useFrame } from '@react-three/fiber';
import { CanvasTexture, PMREMGenerator } from 'three';
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
// 62 degrees above the ground matches a top-down map; aiming at mid-body height
// puts the bus on the road line instead of hovering above it.
const CAMERA_POSITION = [0, -55, 105];
const CAMERA_TARGET = [0, 0, 8];

function AimVehicleCamera() {
  const camera = useThree((state) => state.camera);

  useLayoutEffect(() => {
    camera.position.set(...CAMERA_POSITION);
    camera.up.set(0, 0, 1);
    camera.lookAt(...CAMERA_TARGET);
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

// Seconds for the body to cover most of a turn. A heading that jumps between
// GPS fixes is eased in, so the bus turns instead of snapping round.
const TURN_S = 0.35;
const DEG = Math.PI / 180;
const BLINK_S = 0.7; // ~85 flashes a minute, like a real indicator
const REDUCED_MOTION =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

const clamp = (value, limit) => Math.max(-limit, Math.min(limit, value));
const ease = (current, target, delta, seconds) =>
  current + (target - current) * (1 - Math.exp(-delta / seconds));

function setGlow(materials, intensity) {
  for (const material of materials) material.emissiveIntensity = intensity;
}

// Soft, bus-shaped contact shadow instead of a hard ellipse.
function useShadowTexture() {
  const texture = useMemo(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 256;
    const ctx = canvas.getContext('2d');
    ctx.filter = 'blur(14px)';
    ctx.fillStyle = 'rgba(0,0,0,0.85)';
    ctx.beginPath();
    ctx.roundRect(30, 34, 68, 188, 22);
    ctx.fill();
    return new CanvasTexture(canvas);
  }, []);
  useEffect(() => () => texture.dispose(), [texture]);
  return texture;
}

function VehicleModel({ heading, latitude, longitude, stale, onReady }) {
  const ready = useRef(false);
  const yawRef = useRef(null);
  const bodyRef = useRef(null);
  const brakeRefs = useRef([]);
  const blinkRefs = useRef({ left: [], right: [] });
  const motion = useRef({
    lat: latitude, lng: longitude, speed: 0, accel: 0, yawRate: 0,
    lastYaw: null, signal: 0, signalUntil: 0, clock: 0, brake: 0.8,
  });
  const invalidate = useThree((state) => state.invalidate);
  const shadow = useShadowTexture();
  const targetYaw = -(heading * Math.PI) / 180;
  const [initialYaw] = useState(targetYaw);

  useEffect(() => {
    invalidate();
  }, [targetYaw, latitude, longitude, invalidate]);

  // The lamps whose glow follows the driving, found once by material name.
  useLayoutEffect(() => {
    const lamps = { brake: [], 'blink-left': [], 'blink-right': [] };
    yawRef.current?.traverse((node) => {
      if (lamps[node.material?.name]) lamps[node.material.name].push(node.material);
    });
    brakeRefs.current = lamps.brake;
    blinkRefs.current = { left: lamps['blink-left'], right: lamps['blink-right'] };
  }, []);

  useFrame((_, rawDelta) => {
    const delta = Math.min(rawDelta, 0.1);
    const m = motion.current;
    const yaw = yawRef.current;
    if (!yaw || delta <= 0) return;
    let busy = false;

    // Heading: ease toward the road direction.
    const gap = targetYaw - yaw.rotation.z;
    const diff = Math.atan2(Math.sin(gap), Math.cos(gap));
    if (Math.abs(diff) < 0.002) yaw.rotation.z = targetYaw;
    else {
      yaw.rotation.z += diff * (1 - Math.exp(-delta / TURN_S));
      busy = true;
    }

    // Speed and acceleration from how far the bus moved on the map.
    let metres = 0;
    if (Number.isFinite(latitude) && Number.isFinite(longitude) && Number.isFinite(m.lat)) {
      const kx = 111320 * Math.cos(latitude * DEG);
      metres = Math.hypot((longitude - m.lng) * kx, (latitude - m.lat) * 110574);
    }
    m.lat = latitude;
    m.lng = longitude;
    const speed = ease(m.speed, metres < 200 ? metres / delta : m.speed, delta, 0.6);
    m.accel = ease(m.accel, (speed - m.speed) / delta, delta, 0.5);
    m.speed = speed;

    // Turn rate in degrees a second, + is a right turn.
    const heading = -yaw.rotation.z / DEG;
    if (m.lastYaw != null) {
      const turn = ((heading - m.lastYaw + 540) % 360) - 180;
      m.yawRate = ease(m.yawRate, turn / delta, delta, 0.25);
    }
    m.lastYaw = heading;

    // Brake lights: on while slowing down or standing still.
    const braking = m.speed < 0.6 || m.accel < -0.35;
    m.brake = ease(m.brake, braking ? 2.8 : 0.8, delta, 0.12);
    setGlow(brakeRefs.current, m.brake);

    // Indicator through a bend, held a moment after so it does not flicker.
    m.clock += delta;
    if (!REDUCED_MOTION && Math.abs(m.yawRate) > 7) {
      m.signal = Math.sign(m.yawRate);
      m.signalUntil = m.clock + 0.9;
    } else if (m.clock > m.signalUntil) m.signal = 0;
    const lit = m.signal !== 0 && m.clock % BLINK_S < BLINK_S / 2;
    for (const side of ['left', 'right']) {
      const on = lit && m.signal === (side === 'right' ? 1 : -1);
      setGlow(blinkRefs.current[side], on ? 3 : 0.35);
    }

    // Body leans out of a turn and dips its nose under braking.
    const body = bodyRef.current;
    if (body && !REDUCED_MOTION) {
      const roll = -clamp(m.speed * m.yawRate * 0.0045, 4) * DEG;
      const pitch = clamp(m.accel * 0.9, 2) * DEG;
      body.rotation.y = ease(body.rotation.y, roll, delta, 0.3);
      body.rotation.x = ease(body.rotation.x, pitch, delta, 0.3);
      if (Math.abs(body.rotation.y - roll) > 1e-4 || Math.abs(body.rotation.x - pitch) > 1e-4) busy = true;
    }

    if (busy || m.speed > 0.05 || Math.abs(m.accel) > 0.05 || m.signal !== 0
      || Math.abs(m.brake - (braking ? 2.8 : 0.8)) > 0.01) {
      invalidate();
    }
  });

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
  const sideName = (side) => (side > 0 ? 'right' : 'left');

  return (
    <group ref={yawRef} rotation={[0, 0, initialYaw]}>
      <mesh position={[0, 0, 0.01]} scale={[(W * 1.15 * 128) / 68, (L * 1.06 * 256) / 188, 1]}>
        <planeGeometry args={[1, 1]} />
        <meshBasicMaterial map={shadow} transparent opacity={0.55} depthWrite={false} />
      </mesh>

      <mesh position={[0, 0, 0.3]}>
        <boxGeometry args={[W - 0.12, L - 0.4, 0.22]} />
        <meshStandardMaterial color="#1b2128" roughness={0.9} />
      </mesh>

      {/* Wheels stay on the road; the body above them leans and dips. */}
      {[-1, 1].map((side) =>
        AXLES.map((y) => <Wheel key={`wheel-${side}-${y}`} x={side * (W / 2 - 0.12)} y={y} />),
      )}

      <group ref={bodyRef}>
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
            {/* Indicators: front corner, mirror arm, rear corner */}
            <mesh position={[side * 0.71, FRONT + 0.018, 0.52]}>
              <boxGeometry args={[0.12, 0.04, 0.08]} />
              <meshStandardMaterial name={`blink-${sideName(side)}`} color="#ffb347" emissive="#ff9a1f" emissiveIntensity={0.35} />
            </mesh>
            <mesh position={[side * (W / 2 + 0.012), FRONT - 0.4, 0.86]}>
              <boxGeometry args={[0.03, 0.16, 0.06]} />
              <meshStandardMaterial name={`blink-${sideName(side)}`} color="#ffb347" emissive="#ff9a1f" emissiveIntensity={0.35} />
            </mesh>
            <mesh position={[side * 0.68, -FRONT - 0.012, 0.5]}>
              <boxGeometry args={[0.13, 0.03, 0.08]} />
              <meshStandardMaterial name={`blink-${sideName(side)}`} color="#ffb347" emissive="#ff9a1f" emissiveIntensity={0.35} />
            </mesh>
            <mesh position={[side * (W / 2 + 0.09), FRONT - 0.05, 1.56]}>
              <boxGeometry args={[0.18, 0.03, 0.03]} />
              <meshStandardMaterial color="#14181d" />
            </mesh>
            <mesh position={[side * (W / 2 + 0.18), FRONT - 0.02, 1.42]}>
              <boxGeometry args={[0.05, 0.09, 0.28]} />
              <meshStandardMaterial color="#14181d" roughness={0.4} />
            </mesh>
            {/* Tail and brake light */}
            <mesh position={[side * 0.68, -FRONT - 0.012, 0.74]}>
              <boxGeometry args={[0.13, 0.03, 0.38]} />
              <meshStandardMaterial name="brake" color="#8a0f1c" emissive="#ff1f3d" emissiveIntensity={0.8} />
            </mesh>
          </Fragment>
        ))}
        <mesh position={[0, -FRONT - 0.012, 1.9]}>
          <boxGeometry args={[0.5, 0.03, 0.05]} />
          <meshStandardMaterial name="brake" color="#8a0f1c" emissive="#ff1f3d" emissiveIntensity={0.8} />
        </mesh>
        <mesh position={[0, FRONT + 0.04, 0.4]}>
          <roundedBoxGeometry args={[W + 0.04, 0.16, 0.18, 2, 0.06]} />
          <meshStandardMaterial color="#2a3038" roughness={0.55} />
        </mesh>
        <mesh position={[0, -FRONT - 0.04, 0.4]}>
          <roundedBoxGeometry args={[W + 0.04, 0.16, 0.18, 2, 0.06]} />
          <meshStandardMaterial color="#2a3038" roughness={0.55} />
        </mesh>

        {/* Wheel arches */}
        {[-1, 1].map((side) =>
          AXLES.map((y) => (
            <mesh
              key={`arch-${side}-${y}`}
              position={[side * (W / 2 + 0.008), y, 0.4]}
              rotation={[0, 0, Math.PI / 2]}
            >
              <cylinderGeometry args={[0.43, 0.43, 0.02, 28]} />
              <meshStandardMaterial color="#0e1115" roughness={1} />
            </mesh>
          )),
        )}
      </group>
    </group>
  );
}

function VehicleScene({ heading, latitude, longitude, stale, onReady }) {
  return (
    <>
      <AimVehicleCamera />
      <StudioEnvironment />
      <hemisphereLight args={['#ffffff', '#5b6470', 0.7]} />
      <directionalLight position={[-35, -50, 90]} intensity={1.9} />
      <group position={[0, 0, 0]} scale={10}>
        <VehicleModel
          heading={heading}
          latitude={latitude}
          longitude={longitude}
          stale={stale}
          onReady={onReady}
        />
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
  zoom = 2.3,
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
                zoom,
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
                latitude={snappedPosition?.[0] ?? lat}
                longitude={snappedPosition?.[1] ?? lng}
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
