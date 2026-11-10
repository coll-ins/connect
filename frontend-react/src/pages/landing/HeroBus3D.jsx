import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { CanvasTexture, Color, Object3D, RepeatWrapping, SRGBColorSpace, Vector3 } from 'three';
import { StudioEnvironment, VehicleModel } from '../../components/maps/Vehicle3D';
import matatuPhoto from '../../assets/journeys/bookabus.jpeg';

// A Nairobi street at dusk: the same matatu model the live map uses drives up
// the road to the passenger's stage. `progress` (a ref, 0..1) comes from the
// page scroll, or from the installed app's film clock.
export const STILL = typeof window !== 'undefined'
  && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

const BG = '#0b1215'; // --bg, so the street fades into the page
const ACCENT = '#2ec98a'; // --accent
const STAGE_Y = 34;
const STOP_Y = STAGE_Y - 3.2; // the bus stops with its door at the stage
const DRIVE = [0.5, 0.9]; // scroll range in which the bus drives
const LANE_X = -1.85; // Kenya drives on the left

const clamp01 = (v) => Math.min(1, Math.max(0, v));
const smooth = (t) => t * t * (3 - 2 * t);

// Camera stops, relative to the bus: [progress, position, look-at].
const SHOTS = [
  [0.0, [6.2, 8.4, 2.6], [0, 0.2, 1.05]], // front three-quarter, product shot
  [0.33, [9.6, -0.6, 2.2], [0, -0.2, 1.1]], // side profile: the seats
  [0.66, [2.6, -11, 13], [0, 7, 0]], // above and behind: the route ahead
  [0.94, [-6.4, 10.5, 2.4], [0, 0.4, 1.2]], // from the pavement past the stage, as the rider sees it arrive
];

function shotAt(p, pos, look) {
  let i = 0;
  while (i < SHOTS.length - 2 && p > SHOTS[i + 1][0]) i += 1;
  const [p0, a, la] = SHOTS[i];
  const [p1, b, lb] = SHOTS[i + 1];
  const t = smooth(clamp01((p - p0) / (p1 - p0)));
  pos.set(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t);
  look.set(la[0] + (lb[0] - la[0]) * t, la[1] + (lb[1] - la[1]) * t, la[2] + (lb[2] - la[2]) * t);
}

// Same street on every visit: a fixed-seed random.
function seeded(start) {
  let seed = start;
  return () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
}


// Lit windows, drawn once and shared by every facade.
function useWindowTexture() {
  const texture = useMemo(() => {
    const c = document.createElement('canvas');
    c.width = 64; c.height = 128;
    const g = c.getContext('2d');
    g.fillStyle = '#000'; g.fillRect(0, 0, 64, 128);
    const rand = seeded(7);
    for (let y = 6; y < 128; y += 14) {
      for (let x = 6; x < 64; x += 14) {
        if (rand() < 0.42) continue;
        g.fillStyle = rand() < 0.75 ? '#ffd59a' : '#cfe6ff';
        g.globalAlpha = 0.35 + rand() * 0.65;
        g.fillRect(x, y, 8, 9);
      }
    }
    const t = new CanvasTexture(c);
    t.colorSpace = SRGBColorSpace;
    t.wrapS = RepeatWrapping; t.wrapT = RepeatWrapping;
    return t;
  }, []);
  useEffect(() => () => texture.dispose(), [texture]);
  return texture;
}

// One 60-unit block of street, repeated ahead of and behind the bus so it can
// drive forever. Lamps (every 12) and lane dashes (every 3) divide 60 too.
const TILE = 60;
const BUILDINGS = (() => {
  const list = [];
  const rand = seeded(3);
  for (const side of [-1, 1]) {
    let y = 0;
    while (y < TILE - 4) {
      const depth = 4 + rand() * 4;
      const len = Math.min(4 + rand() * 5, TILE - y - 0.6);
      const h = 3 + rand() * 11;
      list.push({ x: side * (9 + depth / 2 + rand() * 2), y: y + len / 2, w: depth, l: len, h, side, tone: rand() });
      y += len + 0.6 + rand() * 2;
    }
  }
  return list;
})();
const TILES = [-1, 0, 1, 2];

// Every copy of one kind of street part is drawn in a single call, so a
// low-end phone draws ~20 batches instead of ~270 separate meshes.
function Instances({ items, children }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const mesh = ref.current;
    const o = new Object3D();
    const c = new Color();
    items.forEach((it, i) => {
      o.position.set(...it.p);
      o.rotation.set(...(it.r || [0, 0, 0]));
      o.scale.set(...(it.s || [1, 1, 1]));
      o.updateMatrix();
      mesh.setMatrixAt(i, o.matrix);
      if (it.c) mesh.setColorAt(i, c.set(it.c));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [items]);
  return <instancedMesh ref={ref} args={[null, null, items.length]} frustumCulled={false}>{children}</instancedMesh>;
}

const PARTS = (() => {
  const road = []; const kerbs = []; const dashes = []; const poles = []; const lamps = [];
  const blocks = []; const facades = [];
  for (const k of TILES) {
    const o = k * TILE;
    road.push({ p: [0, o + TILE / 2, -0.01] });
    for (const s of [-1, 1]) kerbs.push({ p: [s * 4.6, o + TILE / 2, 0.06] });
    for (let i = 0; i < TILE / 3; i += 1) dashes.push({ p: [0, o + i * 3, 0.002] });
    for (let i = 0; i < TILE / 12; i += 1) {
      poles.push({ p: [5.2, o + i * 12 + 6, 2.4], r: [Math.PI / 2, 0, 0] });
      lamps.push({ p: [4.65, o + i * 12 + 6, 4.75] });
    }
    for (const b of BUILDINGS) {
      blocks.push({ p: [b.x, o + b.y, b.h / 2], s: [b.w, b.l, b.h], c: b.tone < 0.5 ? '#151f25' : '#1b262d' });
      facades.push({
        p: [b.x - (b.side * b.w) / 2 - b.side * 0.01, o + b.y, b.h / 2],
        r: [Math.PI / 2, (-b.side * Math.PI) / 2, 0],
        s: [b.l, b.h, 1],
      });
    }
  }
  return { road, kerbs, dashes, poles, lamps, blocks, facades };
})();

// The street follows the bus a whole block at a time, so nothing visibly jumps.
function Street({ street }) {
  const windows = useWindowTexture();
  return (
    <group ref={street}>
      <mesh position={[0, TILE / 2, -0.03]}>
        <planeGeometry args={[400, 400]} />
        <meshStandardMaterial color="#10181c" roughness={1} />
      </mesh>
      <Instances items={PARTS.road}>
        <planeGeometry args={[7.4, TILE]} />
        <meshStandardMaterial color="#1a2127" roughness={0.9} />
      </Instances>
      <Instances items={PARTS.kerbs}>
        <boxGeometry args={[2.4, TILE, 0.14]} />
        <meshStandardMaterial color="#232c32" roughness={0.95} />
      </Instances>
      <Instances items={PARTS.dashes}>
        <planeGeometry args={[0.1, 1.3]} />
        <meshBasicMaterial color="#c9ced4" transparent opacity={0.45} />
      </Instances>
      <Instances items={PARTS.poles}>
        <cylinderGeometry args={[0.06, 0.08, 4.8, 8]} />
        <meshStandardMaterial color="#2b343b" />
      </Instances>
      <Instances items={PARTS.lamps}>
        <boxGeometry args={[1.2, 0.3, 0.12]} />
        <meshStandardMaterial color="#2b343b" emissive="#ffcf8a" emissiveIntensity={1.6} />
      </Instances>
      <Instances items={PARTS.blocks}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color="#ffffff" roughness={0.95} />
      </Instances>
      {/* The facades facing the road, with lit windows */}
      <Instances items={PARTS.facades}>
        <planeGeometry args={[1, 1]} />
        <meshStandardMaterial color="#141c21" emissive="#ffffff" emissiveMap={windows} emissiveIntensity={0.9} />
      </Instances>
    </group>
  );
}

// The rider: waits under the shelter, then walks to the door and boards.
function Rider({ rider }) {
  return (
    <group ref={rider}>
      <mesh position={[0, 0, 0.62]} rotation={[Math.PI / 2, 0, 0]}>
        <capsuleGeometry args={[0.2, 0.62, 4, 12]} />
        <meshStandardMaterial color="#c8553d" roughness={0.7} />
      </mesh>
      <mesh position={[0, 0, 1.22]}>
        <sphereGeometry args={[0.15, 16, 12]} />
        <meshStandardMaterial color="#6b4430" roughness={0.6} />
      </mesh>
      <mesh position={[-0.2, 0.05, 0.75]}>
        <boxGeometry args={[0.12, 0.3, 0.4]} />
        <meshStandardMaterial color="#2b343b" roughness={0.8} />
      </mesh>
    </group>
  );
}

// The passenger's stage: shelter, bench and the green stage marker.
function Stage({ stage }) {
  return (
    <group ref={stage} position={[-4.4, STAGE_Y, 0.13]}>
      {[-1.6, 1.6].map((y) => (
        <mesh key={y} position={[-0.6, y, 1.2]}>
          <boxGeometry args={[0.1, 0.1, 2.4]} />
          <meshStandardMaterial color="#9aa5ad" metalness={0.6} roughness={0.35} />
        </mesh>
      ))}
      <mesh position={[-0.2, 0, 2.45]}>
        <boxGeometry args={[1.8, 3.8, 0.1]} />
        <meshStandardMaterial color="#d7dde1" roughness={0.4} />
      </mesh>
      <mesh position={[-0.95, 0, 1.3]}>
        <boxGeometry args={[0.05, 3.2, 1.8]} />
        <meshPhysicalMaterial color="#9fc6d6" transparent opacity={0.22} roughness={0.05} />
      </mesh>
      <mesh position={[-0.6, 0, 0.45]}>
        <boxGeometry args={[0.45, 2.4, 0.08]} />
        <meshStandardMaterial color="#5a4632" roughness={0.8} />
      </mesh>
      <mesh position={[2.2, 0, -0.12]}>
        <ringGeometry args={[0.3, 0.55, 40]} />
        <meshBasicMaterial color={ACCENT} />
      </mesh>
    </group>
  );
}

// Frames the street for the layout: on wide screens the bus sits right of the
// words, on phones above them.
function Framing({ frame }) {
  const get = useThree((s) => s.get);
  const size = useThree((s) => s.size);
  useLayoutEffect(() => {
    const { camera } = get();
    const { width: w, height: h } = size;
    camera.fov = w < h ? 44 : 34;
    if (frame === 'center') camera.clearViewOffset();
    else if (w >= 960 || w > h * 1.3) camera.setViewOffset(w, h, -w * 0.22, 0, w, h);
    // Phones: the bus rides in the top half, the words sit under it.
    else camera.setViewOffset(w, h, 0, h * 0.3, w, h);
    camera.updateProjectionMatrix();
  }, [get, size, frame]);
  return null;
}

const CRUISE = 9; // units a second, about 30 km/h for a bus this size
const easeOut = (t) => 1 - (1 - t) ** 2;

function Ride({ progress }) {
  const bus = useRef(null);
  const body = useRef(null);
  const route = useRef(null);
  const street = useRef(null);
  const stage = useRef(null);
  const rider = useRef(null);
  const boarded = useRef(0); // seconds since the bus stopped at the stage
  const camera = useThree((s) => s.camera);
  const aspect = useThree((s) => s.size.width / Math.max(1, s.size.height));
  // A tall phone screen is narrow: step back so the whole bus fits across it.
  const pull = aspect < 1 ? Math.min(1.6, aspect ** -0.6) : 1;
  const shown = useRef(progress.current);
  const clock = useRef(0);
  // How far the bus has cruised, and where it was when it began to slow.
  const drive = useRef({ odo: 0, from: 0 });
  const pos = useMemo(() => new Vector3(), []);
  const look = useMemo(() => new Vector3(), []);

  useFrame((_, raw) => {
    const delta = Math.min(raw, 0.1);
    clock.current += delta;
    const target = progress.current;
    // Eased toward the scroll position, so the camera glides like a dolly. A big
    // jump (the film looping, a jump to the top) is a cut, so the bus never
    // reverses back down the road.
    shown.current = STILL || Math.abs(target - shown.current) > 0.5
      ? target
      : shown.current + (target - shown.current) * (1 - Math.exp(-delta / 0.18));
    const p = shown.current;

    // Before the stop the bus drives on by itself; scrolling on brings it in
    // to the stage, which sits a fixed braking distance ahead of where it began to slow.
    const d = drive.current;
    const f = clamp01((p - DRIVE[0]) / (DRIVE[1] - DRIVE[0]));
    let busY;
    if (f <= 0) {
      if (!STILL) d.odo += CRUISE * delta;
      // Wrap by whole blocks: the street repeats, so this is invisible, and
      // positions stay small enough for float32 on a tab left open for hours.
      if (d.odo > TILE * 100) d.odo -= TILE * 100;
      d.from = d.odo;
      busY = d.odo;
    } else {
      busY = d.from + easeOut(f) * STOP_Y;
      d.odo = busY;
    }
    const stageY = d.from + STAGE_Y;
    const speed = f <= 0 ? CRUISE : (1 - f) * CRUISE;

    if (bus.current) bus.current.position.y = busY;
    // Road feel: a light bounce that dies away as the bus stops.
    if (body.current && !STILL) {
      const shake = Math.min(1, speed / CRUISE);
      body.current.position.z = shake * (Math.sin(clock.current * 17) * 0.012 + Math.sin(clock.current * 5.3) * 0.01);
      body.current.rotation.y = shake * Math.sin(clock.current * 3.1) * 0.004;
    }
    if (street.current) street.current.position.y = Math.floor(busY / TILE) * TILE;
    if (stage.current) stage.current.position.y = stageY;

    // Once the bus has stopped, the rider walks from the shelter to the door.
    boarded.current = f >= 0.995 ? boarded.current + delta : 0;
    if (rider.current) {
      const w = STILL ? (f >= 0.995 ? 1 : 0) : clamp01((boarded.current - 0.5) / 1.8);
      const k = smooth(w);
      const r = rider.current;
      r.visible = w < 1;
      r.position.set(-5 + (LANE_X - 0.95 + 5) * k, stageY + 0.4 + (-1.6 - 0.4) * k, (1 - k) * 0.13);
      r.rotation.z = w > 0 ? Math.atan2(-2, LANE_X - 0.95 + 5) - Math.PI / 2 : 0;
      r.children[0].position.z = 0.62 + (w > 0 && w < 1 ? Math.abs(Math.sin(boarded.current * 9)) * 0.05 : 0);
    }
    if (route.current) {
      const len = Math.max(0.001, stageY - busY - 2.4);
      route.current.scale.y = len;
      route.current.position.y = busY + 2.4 + len / 2;
    }
    shotAt(p, pos, look);
    pos.sub(look).multiplyScalar(pull).add(look);
    // A hand-held camera: it drifts a touch while the bus is moving.
    const sway = STILL ? 0 : Math.min(1, speed / CRUISE) * 0.05;
    // Never back the camera into the buildings along the left kerb.
    camera.position.set(
      Math.max(-7.5, pos.x + LANE_X) + Math.sin(clock.current * 0.7) * sway,
      pos.y + busY,
      pos.z + Math.sin(clock.current * 1.1) * sway,
    );
    camera.lookAt(look.x + LANE_X, look.y + busY, look.z);
  });

  return (
    <>
      <Street street={street} />
      <Stage stage={stage} />
      <Rider rider={rider} />
      {/* The route still to drive, from the bus nose to the stage. */}
      <mesh ref={route} position={[LANE_X, STAGE_Y / 2, 0.004]}>
        <planeGeometry args={[0.16, 1]} />
        <meshBasicMaterial color={ACCENT} />
      </mesh>
      <group ref={bus} position={[LANE_X, 0, 0]}>
        <group ref={body}>
          <VehicleModel heading={0} latitude={0} longitude={0} />
        </group>
      </group>
    </>
  );
}

const COARSE = typeof window !== 'undefined' && window.matchMedia?.('(pointer: coarse)').matches;

export default function HeroBus3D({ progress, frame, paused = false }) {
  const wrap = useRef(null);
  const fallback = useRef(0);
  const [visible, setVisible] = useState(true);
  const [lost, setLost] = useState(false);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return undefined;
    const io = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting));
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // The GPU dropped the scene (low memory, driver reset): show the photo instead.
  if (lost) return <img className="lp-story-photo" src={matatuPhoto} alt="" aria-hidden="true" />;

  return (
    <div ref={wrap} className="lp-3d" aria-hidden="true">
      <Canvas
        frameloop={visible && !paused ? 'always' : 'never'}
        dpr={[1, COARSE ? 1.25 : 1.75]}
        onCreated={({ gl }) => gl.domElement.addEventListener('webglcontextlost', (e) => {
          e.preventDefault();
          setLost(true);
        })}
        camera={{ position: [6, 8, 2.6], up: [0, 0, 1], fov: 34, near: 0.1, far: 140 }}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
      >
        <color attach="background" args={[BG]} />
        <fog attach="fog" args={[BG, 30, 85]} />
        <StudioEnvironment />
        <hemisphereLight args={['#b9c9d6', '#151b20', 0.55]} />
        <directionalLight position={[-8, 6, 14]} intensity={1.6} color="#ffe6c4" />
        <directionalLight position={[10, -12, 6]} intensity={0.5} color="#9bb7ff" />
        <Framing frame={frame} />
        <Ride progress={progress || fallback} />
      </Canvas>
    </div>
  );
}
