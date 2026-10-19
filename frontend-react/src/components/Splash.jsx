import { useEffect, useState } from "react";
import "./Splash.css";

const SHOW_MS = 2600;
const FADE_MS = 500;

export default function Splash() {
  const [visible, setVisible] = useState(() => {
    try { return !sessionStorage.getItem("splashSeen"); } catch { return true; }
  });
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    if (!visible || leaving) return undefined;
    const t = setTimeout(() => setLeaving(true), SHOW_MS);
    return () => clearTimeout(t);
  }, [visible, leaving]);

  useEffect(() => {
    if (!leaving) return undefined;
    try { sessionStorage.setItem("splashSeen", "1"); } catch { /* ignore */ }
    const t = setTimeout(() => setVisible(false), FADE_MS);
    return () => clearTimeout(t);
  }, [leaving]);

  if (!visible) return null;

  return (
    <div className={`splash${leaving ? " leaving" : ""}`} aria-hidden="true">
      <img src="/splash.jpg" alt="" />
      <div className="splash-bar" />
      <button type="button" className="splash-skip" onClick={() => setLeaving(true)}>
        Skip
      </button>
    </div>
  );
}
