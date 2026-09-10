"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Bell, Download, WifiOff, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getStoredToken } from "@/lib/auth";
import { flushOfflineQueue, getOfflineQueueCount } from "@/lib/api";
import { registerPushSubscription, setupPushNotifications } from "@/lib/push";

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export function PwaClientFeatures() {
  const pathname = usePathname();
  const [installPrompt, setInstallPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [offline, setOffline] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [pushPrompt, setPushPrompt] = useState(false);
  const [pushBusy, setPushBusy] = useState(false);
  const [pushError, setPushError] = useState<string | null>(null);
  const [pendingOffline, setPendingOffline] = useState(0);
  const [offlineSyncError, setOfflineSyncError] = useState<string | null>(null);

  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // PWA support is optional; the application remains usable normally.
      });
    }

    const handleBeforeInstall = (event: Event) => {
      event.preventDefault();
      setInstallPrompt(event as BeforeInstallPromptEvent);
    };
    const handleOffline = () => setOffline(true);
    const handleOnline = () => {
      setOffline(false);
      void flushOfflineQueue();
    };
    const refreshQueue = () => setPendingOffline(getOfflineQueueCount());
    const handleQueueError = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail;
      setOfflineSyncError(detail || "Una acción no pudo sincronizarse.");
      refreshQueue();
    };

    setOffline(!navigator.onLine);
    refreshQueue();
    void flushOfflineQueue();
    window.addEventListener("beforeinstallprompt", handleBeforeInstall);
    window.addEventListener("offline", handleOffline);
    window.addEventListener("online", handleOnline);
    window.addEventListener("mantencion:offline-queue", refreshQueue);
    window.addEventListener("mantencion:offline-synced", refreshQueue);
    window.addEventListener("mantencion:offline-sync-error", handleQueueError);
    return () => {
      window.removeEventListener("beforeinstallprompt", handleBeforeInstall);
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("mantencion:offline-queue", refreshQueue);
      window.removeEventListener("mantencion:offline-synced", refreshQueue);
      window.removeEventListener("mantencion:offline-sync-error", handleQueueError);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function checkPush() {
      if (!getStoredToken() || !("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
        return;
      }
      if (Notification.permission === "denied") {
        if (!cancelled) {
          setPushPrompt(true);
          setPushError("El permiso está bloqueado. Actívalo en los ajustes de notificaciones del navegador.");
        }
        return;
      }
      try {
        const registration = await navigator.serviceWorker.ready;
        const subscription = await registration.pushManager.getSubscription();
        if (subscription) {
          // Re-register existing subscriptions after login or a backend restart.
          await registerPushSubscription(subscription);
          if (!cancelled) {
            setPushPrompt(false);
            setPushError(null);
          }
        } else if (!cancelled) {
          setPushPrompt(true);
        }
      } catch {
        if (!cancelled) {
          setPushPrompt(true);
          setPushError("No se pudo registrar este dispositivo. Revisa la conexión e inténtalo nuevamente.");
        }
      }
    }
    void checkPush();
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  async function installApp() {
    if (!installPrompt) return;
    await installPrompt.prompt();
    await installPrompt.userChoice;
    setInstallPrompt(null);
  }

  async function activatePush() {
    if (pushBusy) return;
    setPushBusy(true);
    setPushError(null);
    try {
      const enabled = await setupPushNotifications();
      if (enabled) setPushPrompt(false);
      else setPushError("El permiso de notificaciones no fue concedido.");
    } catch {
      setPushError("No se pudieron activar las notificaciones. Inténtalo nuevamente.");
    } finally {
      setPushBusy(false);
    }
  }

  return (
    <>
      {offline && (
        <div className="fixed inset-x-0 top-0 z-[60] flex items-center justify-center gap-2 bg-amber-100 px-4 py-2 text-center text-xs font-medium text-amber-900 shadow-sm">
          <WifiOff className="h-4 w-4" />
          Sin conexión. Los borradores locales se conservarán y se reintentará al volver Internet.
        </div>
      )}
      {!offline && pendingOffline > 0 && (
        <div className="fixed inset-x-0 top-0 z-[59] flex items-center justify-center gap-2 bg-blue-100 px-4 py-2 text-center text-xs font-medium text-blue-900 shadow-sm">
          Sincronizando {pendingOffline} acción{pendingOffline === 1 ? "" : "es"} pendiente{pendingOffline === 1 ? "" : "s"}...
        </div>
      )}
      {offlineSyncError && (
        <div className="fixed inset-x-4 top-12 z-[59] mx-auto flex max-w-xl items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-900 shadow-sm">
          <span className="min-w-0 flex-1">No se pudo sincronizar una acción offline: {offlineSyncError}</span>
          <button type="button" className="font-semibold underline" onClick={() => setOfflineSyncError(null)}>
            Cerrar
          </button>
        </div>
      )}
      {installPrompt && !dismissed && !offline && (
        <div className="fixed bottom-4 left-4 right-4 z-[60] mx-auto flex max-w-lg items-center gap-3 rounded-xl border bg-card p-3 shadow-lg sm:left-auto sm:right-5">
          <Download className="h-5 w-5 shrink-0 text-primary" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">Instala Mantención</p>
            <p className="text-xs text-muted-foreground">Accede más rápido desde el teléfono.</p>
          </div>
          <Button size="sm" onClick={installApp}>Instalar</Button>
          <button
            type="button"
            aria-label="Cerrar aviso de instalación"
            className="rounded p-1 text-muted-foreground hover:bg-muted"
            onClick={() => setDismissed(true)}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
      {pushPrompt && !offline && (
        <div className="fixed bottom-20 left-4 right-4 z-[60] mx-auto flex max-w-lg items-center gap-3 rounded-xl border bg-card p-3 shadow-lg sm:left-auto sm:right-5">
          <Bell className="h-5 w-5 shrink-0 text-primary" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">Activa las notificaciones</p>
            <p className="text-xs text-muted-foreground">Recibe avisos aunque cierres la aplicación.</p>
            {pushError && <p className="mt-1 text-xs text-destructive">{pushError}</p>}
          </div>
          <Button size="sm" onClick={activatePush} disabled={pushBusy}>
            {pushBusy ? "Activando..." : "Activar"}
          </Button>
          <button
            type="button"
            aria-label="Cerrar aviso de notificaciones"
            className="rounded p-1 text-muted-foreground hover:bg-muted"
            onClick={() => setPushPrompt(false)}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
    </>
  );
}
