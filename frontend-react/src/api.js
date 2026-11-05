const API_BASE_URL = '/api';

function getCookie(name) {
  return document.cookie
    .split('; ')
    .find((row) => row.startsWith(`${name}=`))
    ?.split('=')[1] || null;
}

async function ensureCsrf(signal) {
  if (!getCookie('csrftoken')) {
    await fetch(`${API_BASE_URL}/users/csrf/`, {
      credentials: 'include',
      signal,
    });
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

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? 20000);
  const abortFromCaller = () => controller.abort();
  if (options.signal?.aborted) controller.abort();
  else options.signal?.addEventListener('abort', abortFromCaller, { once: true });

  const config = { ...options, method, headers, credentials: 'include' };
  if (config.body && typeof config.body === 'object' && !bodyIsFormData) {
    config.body = JSON.stringify(config.body);
  }

  let response;
  try {
    if (!['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method)) {
      const csrfToken = await ensureCsrf(controller.signal);
      if (csrfToken) headers['X-CSRFToken'] = decodeURIComponent(csrfToken);
    }

    response = await fetch(url, { ...config, signal: controller.signal });
  } catch (e) {
    throw new Error(
      e?.name === 'AbortError'
        ? 'CONNECT is taking longer than expected. Check your connection and try again.'
        : "We couldn't reach CONNECT. Check your internet connection and try again.",
      { cause: e },
    );
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', abortFromCaller);
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
