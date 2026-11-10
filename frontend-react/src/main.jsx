import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './App.css'
import './styles/touch.css'
import './styles/tokens.css'
import App from './App.jsx'
import Splash from './components/Splash.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Splash />
    <App />
  </StrictMode>,
)

// Kept for the landing page's "Install the app" button, which may mount
// after Chrome has already fired this.
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  window.connectInstallPrompt = e;
  window.dispatchEvent(new Event('connect-install-ready'));
});

// Offline page for the installed app. Skipped in dev so Vite's reloads stay plain.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}
