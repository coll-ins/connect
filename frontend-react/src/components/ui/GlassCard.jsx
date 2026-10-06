export default function GlassCard({
  children,
  className = '',
  as: Component = 'section',
}) {
  return (
    <Component className={`glass-card ${className}`}>
      {children}
    </Component>
  );
}
