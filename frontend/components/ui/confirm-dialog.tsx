"use client";

import { Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * ConfirmDialog — tarjeta de confirmación inline (mismo patrón visual que las
 * confirmaciones actuales de `ordenes/[id]`, pero reutilizable). `children`
 * lleva el campo opcional de motivo/firma. El botón primario se colorea según
 * `tone` (default ok · destructive · success aprobar). El tono del borde
 * superior también lo refleja.
 */
export function ConfirmDialog({
  title,
  description,
  children,
  confirmLabel,
  tone = "default",
  busy = false,
  disabled = false,
  onConfirm,
  onCancel,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  children?: React.ReactNode;
  confirmLabel: string;
  tone?: "default" | "destructive" | "success";
  busy?: boolean;
  disabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  className?: string;
}) {
  return (
    <Card
      className={cn(
        "mb-4 border-blue-200",
        tone === "destructive" && "border-red-200",
        tone === "success" && "border-emerald-200",
        className
      )}
    >
      <CardContent className="p-4">
        <h3 className="font-semibold mb-2">{title}</h3>
        {description && (
          <p className="mb-3 text-sm text-muted-foreground">{description}</p>
        )}
        {children}
        <div className="flex gap-2">
          <Button
            onClick={onConfirm}
            disabled={busy || disabled}
            variant={tone === "destructive" ? "destructive" : "default"}
            className="flex-1"
          >
            {busy && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
            {confirmLabel}
          </Button>
          <Button variant="outline" onClick={onCancel} disabled={busy} className="flex-1">
            <X className="mr-1 h-4 w-4" />
            Cancelar
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
