import { useEffect, useState } from 'react';
import { Download } from 'lucide-react';

// Chrome on Android fires beforeinstallprompt (caught in main.jsx); iPhones
// never do, so Safari users get the two taps instead.
export default function InstallApp() {
  const [prompt, setPrompt] = useState(() => window.connectInstallPrompt || null);
  const [installed, setInstalled] = useState(false);

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
  let body = null;
  if (installed) body = <p>Installed. Open CONNECT from your home screen.</p>;
  else if (prompt) {
    body = (
      <>
        <button type="button" className="btn btn-ghost lp-install-btn" onClick={install}>
          <Download size={18} aria-hidden="true" /> Install the app
        </button>
        <p>Opens from your home screen, full screen, like any app.</p>
      </>
    );
  } else if (/iPhone|iPad|iPod/.test(ua)) body = <p>Get the app: in Safari tap Share, then “Add to Home Screen”.</p>;
  else if (/Android/.test(ua)) body = <p>Get the app: open this page in Chrome, tap ⋮, then “Install app”.</p>;
  return body && <div className="lp-install">{body}</div>;
}
