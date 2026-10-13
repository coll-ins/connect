import { Canvas, useThree } from '@react-three/fiber';
import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

function VehicleModel({ heading, stale, onReady }) {
  const ready = useRef(false);

  const handleAfterRender = useCallback(() => {
    if (ready.current) return;
    ready.current = true;
    onReady?.();
  }, [onReady]);

  return (
    <group rotation={[0, 0, -(heading * Math.PI) / 180]}>
      <mesh position={[0, 0, -0.2]} receiveShadow>
        <circleGeometry args={[2.3, 32]} />
        <meshBasicMaterial
          color={stale ? '#d84343' : '#102a43'}
          transparent
          opacity={0.28}
        />
      </mesh>

      <mesh position={[0, 0, 0.35]} castShadow onAfterRender={handleAfterRender}>
        <boxGeometry args={[2.05, 4.15, 0.9]} />
        <meshStandardMaterial
          color={stale ? '#d84343' : '#f28c28'}
          roughness={0.42}
          metalness={0.12}
        />
      </mesh>

      <mesh position={[0, -0.15, 0.92]} castShadow>
        <boxGeometry args={[1.6, 2.15, 0.48]} />
        <meshStandardMaterial color="#17324d" roughness={0.3} metalness={0.2} />
      </mesh>

      <mesh position={[0, 1.43, 0.87]} castShadow>
        <boxGeometry args={[1.72, 0.72, 0.3]} />
        <meshStandardMaterial color="#ffd166" emissive="#9b6410" emissiveIntensity={0.25} />
      </mesh>

      <mesh position={[0, -1.82, 0.84]} castShadow>
        <boxGeometry args={[1.72, 0.52, 0.28]} />
        <meshStandardMaterial color="#ef476f" emissive="#771c35" emissiveIntensity={0.2} />
      </mesh>

      {[-1, 1].map((side) =>
        [-1, 1].map((axle) => (
          <mesh
            key={`${side}-${axle}`}
            position={[side * 1.06, axle * 1.28, 0.18]}
            castShadow
          >
            <boxGeometry args={[0.42, 0.88, 0.46]} />
            <meshStandardMaterial color="#18212b" roughness={0.8} />
          </mesh>
        )),
      )}
    </group>
  );
}

function VehicleScene({ position, heading, stale, onReady }) {
  const { size } = useThree();

  return (
    <>
      <ambientLight intensity={1.8} />
      <directionalLight position={[-30, 40, 70]} intensity={2.4} />
      <group
        position={[
          position.x - size.width / 2,
          size.height / 2 - position.y,
          0,
        ]}
        scale={10}
      >
        <VehicleModel heading={heading} stale={stale} onReady={onReady} />
      </group>
    </>
  );
}

export default function Vehicle3D({
  map,
  latitude,
  longitude,
  heading,
  stale = false,
  onReady,
}) {
  const [position, setPosition] = useState(null);
  const lat = Number(latitude);
  const lng = Number(longitude);
  const direction = Number(heading);
  const vehicleHeading = Number.isFinite(direction) ? direction : 0;

  useEffect(() => {
    if (!map || !Number.isFinite(lat) || !Number.isFinite(lng)) {
      setPosition(null);
      return undefined;
    }

    const updatePosition = () => {
      const point = map.latLngToContainerPoint([lat, lng]);
      setPosition({ x: point.x, y: point.y });
    };

    updatePosition();
    map.on('move zoom resize viewreset', updatePosition);

    return () => {
      map.off('move zoom resize viewreset', updatePosition);
    };
  }, [lat, lng, map]);

  if (!map || !position) return null;

  return createPortal(
    <Canvas
      orthographic
      camera={{ position: [0, 0, 100], zoom: 1, near: 0.1, far: 200 }}
      dpr={[1, 2]}
      gl={{ alpha: true, antialias: true }}
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 650,
        pointerEvents: 'none',
      }}
    >
      <VehicleScene
        position={position}
        heading={vehicleHeading}
        stale={stale}
        onReady={onReady}
      />
    </Canvas>,
    map.getContainer(),
  );
}
