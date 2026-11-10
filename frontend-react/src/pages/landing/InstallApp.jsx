import { useEffect, useState } from 'react';
import { Download } from 'lucide-react';

// Chrome on Android fires beforeinstallprompt (caught in main.jsx) only when its
// own heuristics allow (not after a dismissal, not on every first visit), and
// iPhones never do. So phones always get the button: Android without a prompt
// downloads the real app (public/connect.apk, built from android/), iPhone gets the Share step.
export default function InstallApp() {
  const [prompt, setPrompt] = useState(() => window.connectInstallPrompt || null);
  const [installed, setInstalled] = useState(false);
  const [steps, setSteps] = useState(false);

  useEffect(() => {
    const ready = () => setPrompt(window.connectInstallPrompt || null);
    const done = () => setInstalled(true);
    window.addEventListener('connect-install-ready', ready);
    window.addEventListener('appinstalled', done);
    return () => {
      window.removeEventListener('connect-install-ready', ready);
      window.removeEventListener('appinstalled', done);
    };
  }, []);

  const install = async () => {
    prompt.prompt();
    const { outcome } = await prompt.userChoice;
    window.connectInstallPrompt = null;
    setPrompt(null);
    if (outcome === 'accepted') setInstalled(true);
  };

  const ua = navigator.userAgent;
  const ios = /iPhone|iPad|iPod/.test(ua);
  const android = /Android/.test(ua);
  // Hidden inside the installed app: standalone (Chrome/TWA) or Android WebView ("; wv)").
  if (window.matchMedia?.('(display-mode: standalone)').matches || navigator.standalone || /; wv\)/.test(ua)) return null;

  const label = <><Download size={18} aria-hidden="true" /> Install the app</>;
  let body = null;
  if (installed) body = <p>Installed. Open CONNECT from your home screen.</p>;
  else if (prompt) {
    body = (
      <>
        <button type="button" className="btn btn-ghost lp-install-btn" onClick={install}>{label}</button>
        <p>Opens from your home screen, full screen, like any app.</p>
      </>
    );
  } else if (android) {
    // No browser install prompt (Firefox, Brave, or Chrome holding it back): hand over the real app.
    body = (
      <>
        <a href="/connect.apk" download="CONNECT.apk" className="btn btn-ghost lp-install-btn" onClick={() => setSteps(true)}>{label}</a>
        <p>{steps ? 'Downloading. Tap CONNECT.apk when it finishes, then Install.' : 'Opens from your home screen, full screen, like any app.'}</p>
      </>
    );
  } else if (ios) {
    body = (
      <>
        <button type="button" className="btn btn-ghost lp-install-btn" onClick={() => setSteps((v) => !v)} aria-expanded={steps}>{label}</button>
        <p>{steps ? 'Tap Share (square with an arrow), then “Add to Home Screen”.' : 'Opens from your home screen, full screen, like any app.'}</p>
      </>
    );
  }
  return body && <div className="lp-install">{body}</div>;
}
