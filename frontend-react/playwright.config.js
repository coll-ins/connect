import process from 'node:process';
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  // CI has no GPU: the 3D bus renders in software and, with parallel workers
  // fighting for CPU, freezes the page for seconds (driver live-location test
  // saw its trip at 0.9 s but drew it after 5 s). One worker removes the race.
  workers: process.env.CI ? 1 : undefined,
  reporter: 'list',
  timeout: 30000,
  expect: { timeout: 5000 },
  use: {
    baseURL: 'http://127.0.0.1:4173',
    channel: 'chrome',
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    // API mocks (page.route) don't see requests a service worker makes.
    serviceWorkers: 'block',
  },
  webServer: {
    // CI tests the production build (built in the step before), which is what
    // users get; dev-mode React is several times slower and skews timings.
    command: process.env.CI
      ? 'npm run preview -- --host 127.0.0.1 --port 4173 --strictPort'
      : 'npm run dev -- --host 127.0.0.1 --port 4173 --strictPort',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
  },
});
