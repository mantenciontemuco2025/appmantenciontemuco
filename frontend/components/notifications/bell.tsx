"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Bell, CheckCheck } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { getStoredToken } from "@/lib/auth";
import { AppNotification } from "@/lib/types";
import { cn } from "@/lib/utils";

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  const diff = Math.max(0, Date.now() - then);
  const min = Math.floor(diff / 60000);
  if (min < 1) return "ahora";
  if (min < 60) return `hace ${min} min`;
  const hours = Math.floor(min / 60);
  if (hours < 24) return `hace ${hours} h`;
  const days = Math.floor(hours / 24);
  return `hace ${days} d`;
}

/** Campanita de notificaciones. Self-contained: lee el token y consulta su
 *  propio estado, por lo que no requiere props adicionales del Shell. */
export function NotificationBell() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<AppNotification[]>([]);
  const [busy, setBusy] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    if (!getStoredToken()) return;
    try {
      const list = await apiFetch<AppNotification[]>("/api/notifications");
      setItems(list);
      setUnread(list.filter((n) => !n.is_read).length);
    } catch {
      // token inválido o servidor caído: silencioso
    }
  }, []);

  // Carga inicial + refresco periódico de respaldo cada 60s.
  useEffect(() => {
    void load();
    const t = setInterval(load, 60000);
    const onFocus = () => void load();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(t);
      window.removeEventListener("focus", onFocus);
    };
  }, [load]);

  // Cerrar al hacer click fuera.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  async function openNotification(n: AppNotification) {
    if (!n.is_read) {
      setUnread((u) => Math.max(0, u - 1));
      setItems((xs) => xs.map((x) => (x.id === n.id ? { ...x, is_read: true } : x)));
      try {
        await apiFetch(`/api/notifications/${n.id}/read`, { method: "POST" });
      } catch {
        // ignorar
      }
    }
    setOpen(false);
    if (n.link) router.push(n.link);
  }

  async function markAllRead() {
    if (busy) return;
    setBusy(true);
    try {
      await apiFetch("/api/notifications/read-all", { method: "POST" });
      setItems((xs) => xs.map((x) => ({ ...x, is_read: true })));
      setUnread(0);
    } catch {
      // ignorar
    } finally {
      setBusy(false);
    }
  }

  const hasAny = items.length > 0;

  return (
    <div className="relative" ref={containerRef}>
      <button
        onClick={() => {
          void load();
          setOpen((o) => !o);
        }}
        className="relative inline-flex items-center justify-center rounded-md px-2.5 py-2 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
        aria-label="Notificaciones"
      >
        <Bell className="h-4 w-4" />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 w-80 max-w-[85vw] rounded-lg border bg-card text-card-foreground shadow-lg z-50">
          <div className="flex items-center justify-between border-b px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold">Notificaciones</span>
              {unread > 0 && <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-800">{unread} sin leer</span>}
            </div>
            {hasAny && (
              <button
                onClick={markAllRead}
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <CheckCheck className="h-3.5 w-3.5" /> Marcar todas
              </button>
            )}
          </div>
          <div className="max-h-80 overflow-y-auto">
            {!hasAny ? (
              <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                Sin notificaciones
              </p>
            ) : (
              <ul className="divide-y">
                {items.map((n) => (
                  <li key={n.id}>
                    <button
                      onClick={() => openNotification(n)}
                      className={cn(
                        "flex w-full flex-col gap-0.5 border-l-4 px-3 py-2.5 text-left transition-colors hover:bg-muted",
                        n.is_read
                          ? "border-l-transparent bg-card text-muted-foreground"
                          : "border-l-blue-500 bg-blue-50/80 text-foreground"
                      )}
                    >
                      <span className="flex items-start gap-2 text-sm leading-snug">
                        {!n.is_read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-blue-600" aria-label="No leída" />}
                        <span className={cn(!n.is_read && "font-semibold")}>{n.message}</span>
                      </span>
                      <span className="text-xs text-muted-foreground">{n.is_read ? "Leída · " : "No leída · "}{timeAgo(n.created_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
