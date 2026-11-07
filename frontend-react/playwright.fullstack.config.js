import process from 'node:process';
import { defineConfig } from '@playwright/test';

// Real Django + real Vite: catches what the mocked e2e suite cannot
// (server 500s, endpoints the UI calls that the backend never serves).
const python = process.env.PYTHON || '.venv/bin/python';

export default defineConfig({
  testDir: './tests/fullstack',
  fullyParallel: false,
  reporter: 'list',
  timeout: 120000,
  use: {
    baseURL: 'http://127.0.0.1:5174',
    channel: 'chrome',
    headless: true,
    trace: 'off',
  },
  webServer: [
    {
      command:
        `rm -f smoke.sqlite3 && ${python} manage.py migrate -v0 && ` +
        `${python} manage.py createcachetable && ${python} manage.py seed_demo && ` +
        `${python} manage.py runserver 127.0.0.1:8000 --noreload`,
      cwd: '../backend',
      url: 'http://127.0.0.1:8000/api/health/',
      reuseExistingServer: false,
      timeout: 120000,
      env: {
        DEBUG: 'True',
        SECRET_KEY: 'fullstack-smoke-only-not-a-real-secret',
        ADMIN_SIGNUP_CODE: 'fullstack-smoke-only-code',
        PAYSTACK_SECRET_KEY: 'sk_test_smoke',
        DATABASE_URL: 'sqlite:///smoke.sqlite3',
        REDIS_URL: '',
        REDIS_CACHE_URL: '',
      },
    },
    {
      command: 'npx vite --host 127.0.0.1 --port 5174 --strictPort',
      url: 'http://127.0.0.1:5174',
      reuseExistingServer: false,
      timeout: 60000,
    },
  ],
});
