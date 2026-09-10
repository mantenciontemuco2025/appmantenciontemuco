"use client";

import { CheckCircle2, Clock, AlertTriangle, RefreshCw, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SyncStatus } from "@/lib/types";

export function SyncBadge({
  status,
  className,
}: {
  status: SyncStatus;
  className?: string;
}) {
  const config = {
    SYNCED: {
      label: "Sincronizado",
      icon: <CheckCircle2 className="h-4 w-4" />,
      classes: "text-emerald-600 bg-emerald-50 border-emerald-200",
    },
    PENDING: {
      label: "En cola",
      icon: <Clock className="h-4 w-4" />,
      classes: "text-amber-600 bg-amber-50 border-amber-200",
    },
    FAILED: {
      label: "Error",
      icon: <AlertTriangle className="h-4 w-4" />,
      classes: "text-red-600 bg-red-50 border-red-200",
    },
  };

  const c = config[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium",
        c.classes,
        className
      )}
    >
      {c.icon}
      {c.label}
    </span>
  );
}

export function RetrySyncButton({
  onRetry,
  loading,
}: {
  onRetry: () => void;
  loading: boolean;
}) {
  return (
    <button
      onClick={onRetry}
      disabled={loading}
      className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-600 hover:bg-blue-100 disabled:opacity-50"
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
      Reintentar
    </button>
  );
}
