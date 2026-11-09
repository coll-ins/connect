// True inside the Play Store app (a Trusted Web Activity) or a home-screen
// install. The TWA's first page load has an android-app:// referrer; later
// loads keep the answer for the rest of the visit.
export function isInstalledApp() {
  try {
    if (sessionStorage.getItem('installedApp') === '1') return true;
    const yes = window.matchMedia('(display-mode: standalone)').matches
      || document.referrer.startsWith('android-app://');
    if (yes) sessionStorage.setItem('installedApp', '1');
    return yes;
  } catch {
    return false;
  }
}
