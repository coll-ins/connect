export function newKey(cryptoImpl = globalThis.crypto) {
  if (typeof cryptoImpl?.randomUUID === 'function') return cryptoImpl.randomUUID();
  // randomUUID only exists in secure contexts; plain-http LAN dev lacks it.
  const bytes = new Uint8Array(16);
  if (typeof cryptoImpl?.getRandomValues === 'function') cryptoImpl.getRandomValues(bytes);
  else for (let i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

// One key per user intent: a retry of the same intent reuses it, a changed
// intent (other trip, seats, pickup) or a success starts a new one.
export function createIntentKeys(generate = newKey) {
  let current = null;
  return {
    keyFor(intent) {
      if (!current || current.intent !== intent) current = { intent, key: generate() };
      return current.key;
    },
    clear() {
      current = null;
    },
  };
}

export const withIdempotencyKey = (body, key) => ({ ...body, idempotency_key: key });
