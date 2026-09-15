"use client";

import {
  clearAuthStorage,
  getStoredRefreshToken,
  getStoredToken,
  updateAccessToken,
} from "./auth-storage";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const QUEUE_KEY = "mantencion:offline-queue";
const CACHE_PREFIX = "mantencion:offline-cache:";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export interface OfflineQueuedResponse {
  __offlineQueued: true;
}

interface OfflineRequest {
  id: string;
  path: string;
  method: string;
  body?: string;
  queuedAt: string;
}

function isBrowser() {
  return typeof window !== "undefined";
}

function readQueue(): OfflineRequest[] {
  if (!isBrowser()) return [];
  try {
    const raw = window.localStorage.getItem(QUEUE_KEY);
    return raw ? (JSON.parse(raw) as OfflineRequest[]) : [];
  } catch {
    return [];
  }
}

function writeQueue(queue: OfflineRequest[]) {
  if (!isBrowser()) return;
  try {
    if (queue.length) window.localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
    else window.localStorage.removeItem(QUEUE_KEY);
    window.dispatchEvent(new CustomEvent("mantencion:offline-queue"));
  } catch {
    // Storage is a safety net; normal online requests still work.
  }
}

function cacheKey(path: string) {
  return `${CACHE_PREFIX}${path}`;
}

function readCache<T>(path: string): T | null {
  if (!isBrowser()) return null;
  try {
    const raw = window.localStorage.getItem(cacheKey(path));
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export function cacheOfflineResponse<T>(path: string, value: T) {
  if (!isBrowser()) return;
  try {
    window.localStorage.setItem(cacheKey(path), JSON.stringify(value));
  } catch {
    // Ignore quota/storage errors.
  }
}

type OnlineCacheEntry = {
  value?: unknown;
  expiresAt: number;
  pending?: Promise<unknown>;
};

// Short-lived in-memory cache for read-only data shared by screens in the same
// tab. It avoids fetching catalogs/workers again when navigating to a form,
// while never persisting user-specific API responses in the browser.
const onlineCache = new Map<string, OnlineCacheEntry>();

export function apiGetCached<T>(path: string, ttlMs: number): Promise<T> {
  const now = Date.now();
  const current = onlineCache.get(path);
  if (current?.pending) return current.pending as Promise<T>;
  if (current && current.expiresAt > now) {
    return Promise.resolve(current.value as T);
  }

  const pending = apiFetch<T>(path)
    .then((value) => {
      onlineCache.set(path, { value, expiresAt: Date.now() + ttlMs });
      return value;
    })
    .catch((error) => {
      onlineCache.delete(path);
      throw error;
    });

  onlineCache.set(path, { expiresAt: 0, pending });
  return pending;
}

export function invalidateApiCache(path: string) {
  for (const key of onlineCache.keys()) {
    if (key === path || key.startsWith(`${path}?`)) onlineCache.delete(key);
  }
}

export function isOfflineQueued(value: unknown): value is OfflineQueuedResponse {
  return Boolean(value && typeof value === "object" && "__offlineQueued" in value);
}

export function getOfflineQueueCount() {
  return readQueue().length;
}

function canQueueMutation(path: string, method: string) {
  return (
    method !== "GET" &&
    method !== "HEAD" &&
    method !== "OPTIONS" &&
    path.startsWith("/api/work-orders/") &&
    !path.endsWith("/sync-google")
  );
}

function queueMutation<T>(path: string, method: string, body?: BodyInit | null): T {
  const request: OfflineRequest = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    path,
    method,
    body: typeof body === "string" ? body : undefined,
    queuedAt: new Date().toISOString(),
  };
  let queue = readQueue();

  // Replace an older autosave for the same OT so we do not replay every keystroke.
  if (path.includes("/fulfill-autosave")) {
    queue = queue.filter((item) => item.path !== path);
  }
  if (path.endsWith("/fulfill")) {
    queue = queue.filter((item) => !item.path.includes("/fulfill-autosave"));
  }
  queue.push(request);
  writeQueue(queue);

  const cachedPath = path.replace(/\/start$|\/complete$|\/fulfill$/, "");
  const cached = readCache<Record<string, unknown>>(cachedPath);
  return { ...(cached || {}), __offlineQueued: true } as T;
}

function requestHeaders(token: string | null, body?: BodyInit | null) {
  const headers: Record<string, string> = {};
  if (!(body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

async function sendQueuedRequest(item: OfflineRequest, token: string) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(`${API_URL}${item.path}`, {
      method: item.method,
      headers: requestHeaders(token, item.body),
      body: item.body,
      signal: controller.signal,
    });
    if (!response.ok) throw new ApiError(`No se pudo sincronizar ${item.path}`, response.status);
    if (response.status !== 204 && item.method !== "DELETE") {
      cacheOfflineResponse(item.path, await response.json());
    }
  } finally {
    window.clearTimeout(timeout);
  }
}

let flushPromise: Promise<void> | null = null;
let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getStoredRefreshToken();
  if (!refreshToken) return null;
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_URL}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
      .then(async (response) => {
        if (!response.ok) {
          if (response.status === 401) clearAuthStorage();
          return null;
        }
        const data = (await response.json()) as {
          access_token: string;
          refresh_token?: string | null;
        };
        updateAccessToken(data.access_token, data.refresh_token || undefined);
        return data.access_token;
      })
      .catch(() => null)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

async function flushQueueInternal() {
  if (!isBrowser() || !navigator.onLine) return;
  const token = getStoredToken();
  if (!token) return;
  for (const item of readQueue()) {
    try {
      await sendQueuedRequest(item, token);
      writeQueue(readQueue().filter((current) => current.id !== item.id));
    } catch (error) {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
        writeQueue(readQueue().filter((current) => current.id !== item.id));
        window.dispatchEvent(new CustomEvent("mantencion:offline-sync-error", { detail: error.message }));
        continue;
      }
      break;
    }
  }
  window.dispatchEvent(new CustomEvent("mantencion:offline-synced"));
}

export function flushOfflineQueue() {
  if (!flushPromise) {
    flushPromise = flushQueueInternal().finally(() => {
      flushPromise = null;
    });
  }
  return flushPromise;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  allowRefresh = true
): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  const canQueue = canQueueMutation(path, method);
  const token = getStoredToken();
  const headers: Record<string, string> = {
    ...requestHeaders(token, options.body),
    ...(options.headers as Record<string, string>),
  };

  if (isBrowser() && !navigator.onLine) {
    if (method === "GET") {
      const cached = readCache<T>(path);
      if (cached !== null) return cached;
      throw new ApiError("Sin conexión y esta pantalla aún no fue guardada en el dispositivo.", 0);
    }
    if (canQueue) return queueMutation<T>(path, method, options.body);
    throw new ApiError("Sin conexión. Esta acción requiere Internet.", 0);
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...options,
      headers,
      signal: options.signal ?? controller.signal,
    });
  } catch (err) {
    if (isBrowser() && canQueue && (!navigator.onLine || err instanceof TypeError)) {
      return queueMutation<T>(path, method, options.body);
    }
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError("El servidor está tardando demasiado. Intenta nuevamente.", 408);
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }

  if (!res.ok) {
    if (
      res.status === 401 &&
      allowRefresh &&
      !path.endsWith("/api/auth/login") &&
      !path.endsWith("/api/auth/refresh")
    ) {
      const refreshedToken = await refreshAccessToken();
      if (refreshedToken) {
        return apiFetch<T>(
          path,
          {
            ...options,
            headers: {
              ...(options.headers as Record<string, string> | undefined),
              Authorization: `Bearer ${refreshedToken}`,
            },
          },
          false
        );
      }
    }
    let detail = "Error en la solicitud";
    try {
      const data = await res.json();
      detail = data.detail || detail;
      if (Array.isArray(data.detail)) detail = data.detail.map((d: { msg?: string }) => d.msg).join(", ");
    } catch {
      // Ignore parse errors.
    }
    throw new ApiError(detail, res.status);
  }

  if (res.status === 204) return undefined as T;
  const data = (await res.json()) as T;
  if (method === "GET") cacheOfflineResponse(path, data);
  return data;
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  getCached: <T>(path: string, ttlMs: number) => apiGetCached<T>(path, ttlMs),
  invalidateCache: (path: string) => invalidateApiCache(path),
  post: <T>(path: string, body?: unknown) => apiFetch<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body: unknown) => apiFetch<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) => apiFetch<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  upload: <T>(path: string, body: FormData) => apiFetch<T>(path, { method: "POST", body }),
  del: <T>(path: string) => apiFetch<T>(path, { method: "DELETE" }),
};
