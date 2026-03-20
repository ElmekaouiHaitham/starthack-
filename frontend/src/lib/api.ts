// src/lib/api.ts
// Client for the ChainIQ FastAPI backend at http://localhost:8000

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const DEFAULT_TIMEOUT_MS = 60_000;

async function fetchWithTimeout(input: string, init: RequestInit, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s.`);
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function analyzeRequestFromBackend(requestDict: object): Promise<unknown> {
  const res = await fetchWithTimeout(`${BASE_URL}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(requestDict),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function analyzeFileFromBackend(file: File): Promise<unknown> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetchWithTimeout(`${BASE_URL}/analyze`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function analyzeStreamRequestFromBackend(requestDict: object): Promise<Response> {
  const res = await fetchWithTimeout(`${BASE_URL}/analyze-stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(requestDict),
  }, 90_000);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return res;
}

export async function analyzeStreamFileFromBackend(file: File): Promise<Response> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetchWithTimeout(`${BASE_URL}/analyze-stream`, {
    method: 'POST',
    body: form,
  }, 90_000);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return res;
}

export async function findBundlesFromBackend(requestsList: object[]): Promise<unknown[]> {
  const res = await fetchWithTimeout(`${BASE_URL}/bundle`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(requestsList),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function checkBackendHealth(): Promise<boolean> {
  try {
    const res = await fetchWithTimeout(`${BASE_URL}/health`, { method: 'GET' }, 8000);
    return res.ok;
  } catch {
    return false;
  }
}

export async function getAnalyticsFromBackend(): Promise<any> {
  const res = await fetchWithTimeout(`${BASE_URL}/analytics`, { method: 'GET' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}
