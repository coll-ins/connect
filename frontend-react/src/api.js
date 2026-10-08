const API_BASE_URL = '/api';

function getCookie(name) {
  return document.cookie
    .split('; ')
    .find((row) => row.startsWith(`${name}=`))
    ?.split('=')[1] || null;
}

async function ensureCsrf() {
  if (!getCookie('csrftoken')) {
    await fetch(`${API_BASE_URL}/users/csrf/`, { credentials: 'include' });
  }
  return getCookie('csrftoken');
}

export async function apiRequest(endpoint, options = {}) {
  const url = `${API_BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;
  const method = (options.method || 'GET').toUpperCase();
  const headers = { Accept: 'application/json', ...(options.headers || {}) };
  const bodyIsFormData = options.body instanceof FormData;

  if (!bodyIsFormData && options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  if (!['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method)) {
    const csrfToken = await ensureCsrf();
    if (csrfToken) headers['X-CSRFToken'] = decodeURIComponent(csrfToken);
  }

  const config = { ...options, method, headers, credentials: 'include' };
  if (config.body && typeof config.body === 'object' && !bodyIsFormData) {
    config.body = JSON.stringify(config.body);
  }

  let response;
  try {
    response = await fetch(url, config);
  } catch {
    throw new Error('Unable to connect to CONNECT. Make sure Django is running.');
  }

  const contentType = response.headers.get('content-type') || '';
  let data;
  if (contentType.includes('application/json')) {
    try { data = await response.json(); } catch { data = null; }
  } else {
    try { data = await response.text(); } catch { data = null; }
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    if (data && typeof data === 'object') {
      if (typeof data.error === 'string') message = data.error;
      else if (typeof data.detail === 'string') message = data.detail;
      else {
        const first = Object.values(data).find((v) => Array.isArray(v) ? v.length : typeof v === 'string');
        message = Array.isArray(first) ? first[0] : (first || message);
      }
    }
    const error = new Error(message);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}
