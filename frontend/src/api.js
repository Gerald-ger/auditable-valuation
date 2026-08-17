// Relative on purpose: Vite proxies /api to the backend (see vite.config.js), so
// these are same-origin requests and no CORS handshake is involved. Pointing this
// at an absolute host is what made a shifted dev-server port fail silently.
const BASE = '/api';

async function handle(res) {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || res.statusText);
  return body;
}

export const get = (path) => fetch(`${BASE}${path}`).then(handle);

export const post = (path, body) =>
  fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  }).then(handle);

export const patch = (path, body) =>
  fetch(`${BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  }).then(handle);

export const del = (path) => fetch(`${BASE}${path}`, { method: 'DELETE' }).then(handle);

/**
 * Consume a newline-delimited JSON stream from an AI endpoint.
 *
 * A 7B model on CPU takes minutes to finish a reply; without this the UI just
 * sat there. onEvent fires per line as the model produces it — either
 * `{ delta, stage? }` or a terminal `{ error, message }`.
 */
export async function stream(path, body, onEvent) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop(); // a chunk can split mid-line; keep the remainder
    for (const line of lines) {
      if (line.trim()) onEvent(JSON.parse(line));
    }
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer));
}
