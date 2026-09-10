"use client";

import { AlertCircle, CheckCircle2, Info, XCircle, X } from "lucide-react";
import { cn } from "@/lib/utils";

type Variant = "info" | "success" | "warning" | "error";

const CONFIG: Record<Variant, { icon: React.ReactNode; classes: string }> = {
  info: { icon: <Info className="h-4 w-4" />, classes: "border-blue-200 bg-blue-50 text-blue-800" },
  success: { icon: <CheckCircle2 className="h-4 w-4" />, classes: "border-emerald-200 bg-emerald-50 text-emerald-800" },
  warning: { icon: <AlertCircle className="h-4 w-4" />, classes: "border-amber-200 bg-amber-50 text-amber-800" },
  error: { icon: <XCircle className="h-4 w-4" />, classes: "border-red-200 bg-red-50 text-red-800" },
};

/**
 * InlineAlert — banner de feedback inline reutilizable (reemplaza los alert()).
 * Si onDismiss se entrega, muestra un botón de cierre.
 */
export function InlineAlert({
  variant = "info",
  children,
  onDismiss,
  className,
}: {
  variant?: Variant;
  children: React.ReactNode;
  onDismiss?: () => void;
  className?: string;
}) {
  const c = CONFIG[variant];
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm",
        c.classes,
        className
      )}
    >
      <span className="mt-px shrink-0">{c.icon}</span>
      <div className="flex-1 min-w-0">{children}</div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Cerrar aviso"
          className="shrink-0 rounded p-0.5 opacity-70 transition-opacity hover:opacity-100"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}