"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { ApiError, apiFetch } from "./api";
import type { UserRole } from "./types";
import {
  clearAuthStorage,
  getStoredToken as getTokenFromStorage,
  getStoredUser,
  setStoredUser,
  storeAuthTokens,
} from "./auth-storage";

export { getStoredToken, setStoredUser } from "./auth-storage";

export interface AuthUser {
  id: number;
  full_name: string;
  email: string;
  role: UserRole;
  area_id: number | null;
  area_name: string | null;
  area_ids: number[];
  area_names: string[];
  is_active: boolean;
  signature: string | null;
  created_at: string;
  updated_at: string;
}

export function clearAuth() {
  clearAuthStorage();
}

export async function login(
  email: string,
  password: string,
  remember = false
): Promise<AuthUser> {
  const form = new URLSearchParams();
  form.append("username", email);
  form.append("password", password);
  form.append("remember", remember ? "true" : "false");

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/auth/login`,
    {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(),
    }
  );

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Error al iniciar sesión");
  }

  const data = await res.json();
  storeAuthTokens(data.access_token, data.refresh_token || null, remember);
  const me = await apiFetch<AuthUser>("/api/auth/me");
  setStoredUser(me);
  return me;
}

export function getAuthUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  return getStoredUser<AuthUser>();
}

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    const token = getTokenFromStorage();
    const storedUser = getAuthUser();
    if (!token) {
      setLoading(false);
      return;
    }

    if (storedUser) {
      setUser(storedUser);
      setLoading(false);
    }

    apiFetch<AuthUser>("/api/auth/me")
      .then((me) => {
        setStoredUser(me);
        setUser(me);
      })
      .catch((error) => {
        if (storedUser && (!(error instanceof ApiError) || ![401, 403].includes(error.status))) {
          setUser(storedUser);
          return;
        }
        clearAuth();
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const logout = useCallback(() => {
    clearAuth();
    setUser(null);
    router.push("/login");
  }, [router]);

  return { user, loading, logout, setUser };
}
