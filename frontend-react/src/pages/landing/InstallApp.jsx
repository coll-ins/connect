import { useEffect, useState } from 'react';
import { Download } from 'lucide-react';

// Chrome on Android fires beforeinstallprompt (caught in main.jsx) only when its
// own heuristics allow (not after a dismissal, not on every first visit), and
// iPhones never do. So phones always get the button; without a prompt it shows the steps.
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
    if (!prompt) return setSteps((v) => !v);
    prompt.prompt();
    const { outcome } = await prompt.userChoice;
    window.connectInstallPrompt = null;
    setPrompt(null);
    if (outcome === 'accepted') setInstalled(true);
  };

  const ua = navigator.userAgent;
  const ios = /iPhone|iPad|iPod/.test(ua);
  const android = /Android/.test(ua);
  if (window.matchMedia?.('(display-mode: standalone)').matches || navigator.standalone) return null;

  let body = null;
  if (installed) body = <p>Installed. Open CONNECT from your home screen.</p>;
  else if (prompt || ios || android) {
    body = (
      <>
        <button type="button" className="btn btn-ghost lp-install-btn" onClick={install} aria-expanded={prompt ? undefined : steps}>
          <Download size={18} aria-hidden="true" /> Install the app
        </button>
        <p>Opens from your home screen, full screen, like any app.</p>
        {steps && !prompt && (
          <ol className="lp-install-steps">
            {ios ? (
              <>
                <li>In Safari, tap Share (the square with an arrow).</li>
                <li>Tap “Add to Home Screen”.</li>
                <li>Tap Add.</li>
              </>
            ) : (
              <>
                <li>In Chrome, tap ⋮ at the top right.</li>
                <li>Tap “Install app”. If you only see “Add to Home screen”, tap it, then pick Install, not “Create shortcut”.</li>
                <li>Tap Install. CONNECT then shows in your app drawer and opens without the Chrome address bar.</li>
              </>
            )}
          </ol>
        )}
      </>
    );
  }
  return body && <div className="lp-install">{body}</div>;
}
