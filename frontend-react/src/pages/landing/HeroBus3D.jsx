import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { useEffect, useRef, useState } from 'react';
import { StudioEnvironment, VehicleModel } from '../../components/maps/Vehicle3D';

// The same matatu model the live map uses, parked on its route. Scrolling
// turns it and the pointer nudges it; nothing moves on its own when the
// visitor asked for reduced motion. A parent that pins the scene while the
// page scrolls passes its own 0-1 `progress` ref and a wider `turn`.
const STILL = typeof window !== 'undefined'
  && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

function Turntable({ input, progress, turn }) {
  const group = useRef(null);
  // The camera keeps its height, so a tall phone canvas would crop the bus ends.
  const fit = useThree((s) => Math.min(1, s.viewport.aspect / 0.8));
  useFrame((_, rawDelta) => {
    const g = group.current;
    if (!g) return;
    const delta = Math.min(rawDelta, 0.1);
    const { px, py } = input.current;
    const scroll = progress ? progress.current : input.current.scroll;
    const yaw = -0.75 + scroll * turn + px * 0.18;
    const k = 1 - Math.exp(-delta / 0.35);
    g.rotation.z += (yaw - g.rotation.z) * k;
    g.rotation.x += (py * 0.04 - g.rotation.x) * k;
  });
  return (
    <group ref={group} rotation={[0, 0, -0.75]} scale={fit}>
      <Road />
      <VehicleModel heading={0} latitude={0} longitude={0} />
    </group>
  );
}

function Road() {
  const dashes = [-15, -12, -9, -6, -3, 3, 6, 9, 15, 18];
  return (
    <group>
      <mesh position={[0, 0, -0.02]}>
        <planeGeometry args={[240, 240]} />
        {/* Untoned so it is exactly the page's stage colour and no edge shows. */}
        <meshBasicMaterial color="#121b21" toneMapped={false} />
      </mesh>
      <mesh position={[0, 0, -0.01]}>
        <planeGeometry args={[7, 80]} />
        <meshStandardMaterial color="#1c2229" roughness={0.95} />
      </mesh>
      {dashes.map((y) => (
        <mesh key={y} position={[-1.75, y, 0.002]}>
          <planeGeometry args={[0.08, 1.2]} />
          <meshBasicMaterial color="#c9ced4" transparent opacity={0.5} />
        </mesh>
      ))}
      {/* The route line ahead of the bus, ending at the passenger's stage. */}
      <mesh position={[0, 7.2, 0.004]}>
        <planeGeometry args={[0.16, 9]} />
        <meshBasicMaterial color="#1ec98c" />
      </mesh>
      <mesh position={[0, 11.8, 0.006]}>
        <circleGeometry args={[0.42, 40]} />
        <meshBasicMaterial color="#1ec98c" />
      </mesh>
      <mesh position={[0, 11.8, 0.008]}>
        <circleGeometry args={[0.2, 32]} />
        <meshBasicMaterial color="#0d1418" />
      </mesh>
    </group>
  );
}

export default function HeroBus3D({ progress, turn = 1.1 }) {
  const wrap = useRef(null);
  const input = useRef({ scroll: 0, px: 0, py: 0 });
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return undefined;
    const io = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting));
    io.observe(el);
    if (STILL) return () => io.disconnect();
    const onScroll = () => {
      const r = el.getBoundingClientRect();
      input.current.scroll = Math.min(1, Math.max(0, -r.top / Math.max(1, r.height)));
    };
    const onPointer = (e) => {
      input.current.px = (e.clientX / window.innerWidth) * 2 - 1;
      input.current.py = (e.clientY / window.innerHeight) * 2 - 1;
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('pointermove', onPointer, { passive: true });
    onScroll();
    return () => {
      io.disconnect();
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('pointermove', onPointer);
    };
  }, []);

  return (
    <div ref={wrap} className="lp-3d" aria-hidden="true">
      <Canvas
        frameloop={visible && !STILL ? 'always' : 'demand'}
        dpr={[1, 2]}
        camera={{ position: [11, -14, 10.5], up: [0, 0, 1], fov: 27, near: 0.1, far: 160 }}
        onCreated={({ camera }) => camera.lookAt(0.6, -1.2, -0.9)}
        gl={{ alpha: true, antialias: true }}
      >
        <StudioEnvironment />
        <hemisphereLight args={['#ffffff', '#4b5560', 0.7]} />
        <directionalLight position={[-6, -8, 12]} intensity={2} />
        <Turntable input={input} progress={progress} turn={turn} />
      </Canvas>
    </div>
  );
}
