import { useEffect, useState } from "react";
import "./Splash.css";

const SHOW_MS = 1800;
const FADE_MS = 500;

// Like a ride app opening: shown once per browser session to someone already
// signed in on this device, while the app lets them straight in. A new
// visitor goes straight to the login form, and automated browsers skip it.
function shouldShow() {
  try {
    return (
      !navigator.webdriver &&
      Boolean(localStorage.getItem("user_session")) &&
      !sessionStorage.getItem("splashSeen")
    );
  } catch {
    return false;
  }
}

export default function Splash() {
  const [visible, setVisible] = useState(shouldShow);
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
      <picture className="splash-picture">
        <source media="(max-aspect-ratio: 4/5)" srcSet="/splash-mobile.jpg" />
        <img src="/splash.jpg" alt="" />
      </picture>
      <div className="splash-bar" />
      <button type="button" className="splash-skip" onClick={() => setLeaving(true)}>
        Skip
      </button>
    </div>
  );
}
