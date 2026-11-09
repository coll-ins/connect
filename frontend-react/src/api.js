const API_ORIGIN = import.meta.env.VITE_API_URL?.trim().replace(/\/+$/, '') || '';
export const API_HOST = API_ORIGIN ? new URL(API_ORIGIN).host : '';
const API_BASE_URL = API_ORIGIN ? `${API_ORIGIN}/api` : '/api';
let latestRequestError = '';

export function notifyRequestError(message) {
  latestRequestError = message;
  window.dispatchEvent(
    new CustomEvent('connect:request-error', { detail: { message } }),
  );
}

export function getLatestRequestError() {
  return latestRequestError;
}

export function clearRequestError() {
  latestRequestError = '';
}

function getErrorMessage(status, data) {
  if (status === 401) {
    if (typeof data?.error === 'string') return data.error;
    return 'Your session may have expired. Please sign in and try again.';
  }
  if (status === 403) {
    if (typeof data?.error === 'string') return data.error;
    if (typeof data?.detail === 'string') return data.detail;
    return 'You don’t have permission to do that. Please check your account and try again.';
  }
  if (status === 404) {
    return 'We couldn’t find what you’re looking for. Please refresh and try again.';
  }
  if (status === 405) {
    return 'That action isn’t available right now. Please try again later.';
  }
  if (status === 408) {
    return 'That took too long. Please try again.';
  }
  if (status === 429) {
    return 'You’ve tried too many times. Please wait a little and try again.';
  }
  if (status >= 500) {
    return 'Something went wrong on our end. Please try again shortly.';
  }

  if (data && typeof data === 'object') {
    if (typeof data.error === 'string') return data.error;
    if (typeof data.detail === 'string') return data.detail;
    const first = Object.values(data).find((value) =>
      Array.isArray(value) ? value.length : typeof value === 'string'
    );
    if (Array.isArray(first) && typeof first[0] === 'string') return first[0];
    if (typeof first === 'string') return first;
  }

  return 'We couldn’t complete that. Please try again.';
}

function getCookie(name) {
  return document.cookie
    .split('; ')
    .find((row) => row.startsWith(`${name}=`))
    ?.split('=')[1] || null;
}

async function ensureCsrf(signal) {
  const cookie = getCookie('csrftoken');
  if (cookie) return decodeURIComponent(cookie);

  const response = await fetch(`${API_BASE_URL}/users/csrf/`, {
    credentials: 'include',
    signal,
  });
  const data = await response.json();
  if (!response.ok || !data?.csrfToken) {
    throw new Error('Unable to establish a secure connection to CONNECT.');
  }
  return data.csrfToken;
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
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? 65000);
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
      if (csrfToken) headers['X-CSRFToken'] = csrfToken;
    }

    response = await fetch(url, { ...config, signal: controller.signal });
  } catch (e) {
    const message = e?.name === 'AbortError'
      ? 'CONNECT is taking longer than expected. Check your connection and try again.'
      : "We couldn't reach CONNECT. Check your internet connection and try again.";
    if (!options.silent) notifyRequestError(message);
    throw new Error(message, { cause: e });
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

  if (response.ok && contentType.includes('text/html')) {
    const message = 'We couldn’t load your account. Please refresh and try again.';
    notifyRequestError(message);
    throw new Error(message);
  }

  if (!response.ok) {
    const message = getErrorMessage(response.status, data);
    if (!options.silent) notifyRequestError(message);
    const error = new Error(message);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}
