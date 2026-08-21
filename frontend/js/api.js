async function request(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    ...options,
  });
  let payload = null;
  try {
    payload = await res.json();
  } catch {
    payload = null;
  }
  if (!res.ok) {
    // FastAPI puts validation errors in a list; surface the first readable one
    // rather than "[object Object]".
    const detail = payload?.detail;
    const message = Array.isArray(detail)
      ? (detail[0]?.msg ?? 'Requête invalide.')
      : (detail ?? `Erreur ${res.status}`);
    const error = new Error(message);
    error.status = res.status;
    throw error;
  }
  return payload;
}

export const api = {
  content: () => request('/api/content'),
  availability: () => request('/api/availability'),
  book: (body) => request('/api/bookings', { method: 'POST', body: JSON.stringify(body) }),
  quote: (body) => request('/api/quotes', { method: 'POST', body: JSON.stringify(body) }),
};

export { request };
