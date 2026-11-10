import { apiRequest } from '../api';

// Bus alerts that reach the phone while CONNECT is closed (Web Push).

export function pushSupported() {
  return typeof window !== 'undefined'
    && 'serviceWorker' in navigator
    && 'PushManager' in window
    && 'Notification' in window;
}

export function pushPermission() {
  return pushSupported() ? Notification.permission : 'unsupported';
}

// `ready` never settles when no service worker is registered (dev server).
function swReady() {
  return Promise.race([
    navigator.serviceWorker.ready,
    new Promise((_, reject) => setTimeout(() => reject(new Error('No service worker')), 5000)),
  ]);
}

function toBytes(base64url) {
  const pad = '='.repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob((base64url + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

// Save this phone for alerts. Asks for permission only when `ask` is true,
// so it must then run from a tap. Returns true when alerts are on.
export async function enablePush({ ask = false } = {}) {
  if (!pushSupported()) return false;
  let permission = Notification.permission;
  if (permission === 'default' && ask) permission = await Notification.requestPermission();
  if (permission !== 'granted') return false;

  const registration = await swReady();
  const { public_key: key } = await apiRequest('/users/push/', { silent: true });
  let subscription = await registration.pushManager.getSubscription();
  const current = subscription?.options?.applicationServerKey;
  if (subscription && current && btoa(String.fromCharCode(...new Uint8Array(current)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '') !== key) {
    // The server key changed (new SECRET_KEY): the old subscription is dead.
    await subscription.unsubscribe();
    subscription = null;
  }
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: toBytes(key),
    });
  }
  await apiRequest('/users/push/', { method: 'POST', body: subscription.toJSON(), silent: true });
  return true;
}

// Show a notification from an open page. Android Chrome has no
// `new Notification()`, so it goes through the service worker.
export async function showLocalNotification(title, body, tag) {
  if (pushPermission() !== 'granted') return;
  try {
    const registration = await swReady();
    await registration.showNotification(title, { body, tag, icon: '/icon-192.png' });
  } catch {
    // Alerts are a convenience; the live map still shows the bus.
  }
}
