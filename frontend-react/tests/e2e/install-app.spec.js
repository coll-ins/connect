import { expect, test } from '@playwright/test';

async function signedOut(page) {
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/users/csrf/') return route.fulfill({ json: { csrfToken: 'e2e' } });
    return route.fulfill({ status: 401, json: { error: 'Not signed in.' } });
  });
}

test.describe('android', () => {
  test.use({ userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36', viewport: { width: 390, height: 844 } });

  test('Chrome install prompt becomes an Install the app button', async ({ page }) => {
    await signedOut(page);
    await page.goto('/');
    const apk = page.getByRole('link', { name: 'Install the app' });
    await expect(apk).toHaveAttribute('href', '/connect.apk');
    await page.evaluate(() => {
      const e = new Event('beforeinstallprompt', { cancelable: true });
      e.prompt = () => { window.prompted = true; };
      e.userChoice = Promise.resolve({ outcome: 'accepted' });
      window.dispatchEvent(e);
    });
    await page.getByRole('button', { name: 'Install the app' }).click();
    await expect(page.getByText('Installed. Open CONNECT from your home screen.')).toBeVisible();
    expect(await page.evaluate(() => window.prompted)).toBe(true);
    await page.screenshot({ path: 'test-results/install-android.png' });
  });

  test('Without a browser prompt, Install the app downloads the APK', async ({ page }) => {
    await signedOut(page);
    await page.goto('/');
    const [file] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('link', { name: 'Install the app' }).click(),
    ]);
    expect(file.suggestedFilename()).toBe('connect.apk');
    await expect(page.getByText('Tap connect.apk when it finishes, then Install.')).toBeVisible();
  });
});

test.describe('iphone', () => {
  test.use({ userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1', viewport: { width: 390, height: 844 } });

  test('iPhone gets the Share, Add to Home Screen steps', async ({ page }) => {
    await signedOut(page);
    await page.goto('/');
    await page.getByRole('button', { name: 'Install the app' }).click();
    await expect(page.getByText('Tap Share (square with an arrow), then “Add to Home Screen”.')).toBeVisible();
    await page.screenshot({ path: 'test-results/install-iphone.png' });
  });
});
