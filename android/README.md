# CONNECT on Google Play

The Android app is a Trusted Web Activity (TWA): a thin Android shell that opens
https://connect-zj9i-gamma.vercel.app full screen, with no browser bar. Every web
deploy updates the app; a new Play upload is only needed to change the icon, name
or package settings. Sign-in cookies keep working because the app stays on the
same origin as the website.

## Before you start

- Play Console developer account: one-time USD 25.
- New personal accounts must run a **closed test with at least 12 testers for 14
  days in a row** before Play lets you publish to everyone. Line up 12 people
  with Android phones (Gmail addresses) before you upload.
- `packageId` in `twa-manifest.json` (`ke.connectmatatu.app`) is permanent once
  uploaded. Change it now if you want a different one, and in
  `assetlinks.template.json` too.

## Build the app bundle (on your laptop)

Needs Node 18+. Bubblewrap downloads its own JDK and Android SDK on first run.

```bash
npm i -g @bubblewrap/cli
```

```bash
cd android && bubblewrap init --manifest https://connect-zj9i-gamma.vercel.app/manifest.webmanifest
```

When it asks, keep the answers in `twa-manifest.json` (package id, colours) and
let it create the signing key `connect-upload.keystore`. Back that file and its
passwords up somewhere safe (password manager + a USB stick). It is git-ignored.

```bash
bubblewrap build
```

This writes `app-release-bundle.aab` (upload this to Play) and
`app-release-signed.apk` (install on your own phone to test).

## Link the site to the app (removes the browser bar)

1. Upload the `.aab` to a closed test track in Play Console.
2. Play Console → your app → Test and release → App integrity → App signing:
   copy the **SHA-256 certificate fingerprint of the app signing key**.
3. Copy `assetlinks.template.json` to
   `frontend-react/public/.well-known/assetlinks.json`, paste the fingerprint,
   commit and deploy.
4. Check it: `https://connect-zj9i-gamma.vercel.app/.well-known/assetlinks.json`
   returns the JSON (not the app page).

Until step 3 is live, the app works but shows a thin browser bar at the top.

## Play Console answers

- Privacy policy URL: https://connect-zj9i-gamma.vercel.app/legal/privacy
- Account deletion URL: https://connect-zj9i-gamma.vercel.app/legal/delete-account
  (in-app: Profile → Close account).
- App access: give reviewers a working passenger login (phone + password).
- Data safety: collects name, phone number, approximate and precise location
  (live map, only while open), purchase history. Card and M-PESA details are
  handled by Paystack, not stored by CONNECT. Encrypted in transit. Users can
  request deletion.
- Payments: seats, parcels and bus hire are physical services, so Google Play
  Billing is not required; Paystack checkout is allowed.
- Category: Travel & Local. Content rating questionnaire: no violence, no
  user-to-user chat.

## Releasing an update to the shell

Bump `appVersionCode` (+1) and `appVersionName` in `twa-manifest.json`, then
`bubblewrap update && bubblewrap build`, and upload the new `.aab`.

## Direct download APK (live now, no Play Store)

`apk/` is a hand-built TWA (android-browser-helper) of the same app. The landing page's
Install button downloads it from `frontend-react/public/connect.apk` when the browser gives
no install prompt (Firefox, Brave, Chrome holding back). Phones with no TWA browser open it
in a WebView. It is signed with a sideload key kept outside git (`connect-release.jks`);
its SHA-256 is in `frontend-react/public/.well-known/assetlinks.json`.

Rebuild (bump `versionCode` in `apk/app/build.gradle` first, or phones won't update):

```bash
cd android/apk
export ANDROID_HOME=/path/to/android-sdk CONNECT_KEYSTORE=/path/to/connect-release.jks CONNECT_KEYSTORE_PASSWORD=...
./gradlew assembleRelease
cp app/build/outputs/apk/release/app-release.apk ../../frontend-react/public/connect.apk
```

When the Play version ships, add its app-signing SHA-256 to `assetlinks.json` (keep this
one). Same package id, different key: phones with this APK must uninstall it once before
installing from Play.
