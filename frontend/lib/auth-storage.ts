"use client";

const TOKEN_KEY = "mantencion_token";
const REFRESH_TOKEN_KEY = "mantencion_refresh_token";
const USER_KEY = "mantencion_user";
const REMEMBER_KEY = "mantencion_remember_session";

function storageForToken(): Storage | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY) ? localStorage : sessionStorage;
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY);
}

export function getStoredRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(REFRESH_TOKEN_KEY) || sessionStorage.getItem(REFRESH_TOKEN_KEY);
}

export function storeAuthTokens(accessToken: string, refreshToken: string | null, remember: boolean) {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);

  const storage = remember ? localStorage : sessionStorage;
  storage.setItem(TOKEN_KEY, accessToken);
  if (refreshToken) storage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  if (remember) localStorage.setItem(REMEMBER_KEY, "1");
}

export function updateAccessToken(accessToken: string, refreshToken?: string) {
  const storage = storageForToken();
  if (!storage) return;
  storage.setItem(TOKEN_KEY, accessToken);
  if (refreshToken) storage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function clearAuthStorage() {
  if (typeof window === "undefined") return;
  for (const storage of [localStorage, sessionStorage]) {
    storage.removeItem(TOKEN_KEY);
    storage.removeItem(REFRESH_TOKEN_KEY);
    storage.removeItem(USER_KEY);
    storage.removeItem(REMEMBER_KEY);
  }
}

export function setStoredUser(user: unknown) {
  storageForToken()?.setItem(USER_KEY, JSON.stringify(user));
}

export function getStoredUser<T>(): T | null {
  const storage = storageForToken();
  const raw = storage?.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    storage?.removeItem(USER_KEY);
    return null;
  }
}
