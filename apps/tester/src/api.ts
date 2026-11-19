export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: init?.body
      ? { 'content-type': 'application/json', ...(init.headers || {}) }
      : init?.headers,
  });
  const text = await response.text();
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) throw new Error(body?.error || response.statusText);
  return body as T;
}
