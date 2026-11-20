// Shared mock for the company screens. `handler(path, request)` returns
// { status, body } for the endpoints a test cares about, or undefined for the
// default empty list. Every request is recorded in `calls`.
export const testUser = (role) => ({
  id: 17,
  username: 'connect_e2e_user',
  name: 'CONNECT Test User',
  role,
  company_id: 17,
  company_name: 'Test Company',
});

export async function openCompanyPage(page, role, path, handler = () => undefined, user = testUser(role)) {
  const calls = [];
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const respond = (status, body) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });

    if (url.pathname === '/api/users/csrf/') return respond(200, { csrfToken: 'e2e-csrf-token' });
    if (url.pathname === '/api/users/profile/') return respond(200, { user });

    calls.push(`${request.method()} ${url.pathname}${url.search}`);
    const custom = handler(url.pathname, request, url);
    if (custom) return respond(custom.status ?? 200, custom.body);
    return respond(200, []);
  });
  await page.addInitScript((u) => {
    localStorage.setItem('user_session', JSON.stringify(u));
  }, user);
  await page.goto(path);
  return calls;
}

export function collectPageErrors(page) {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  return errors;
}
