"use client";

import { cn } from "@/lib/utils";
import type { WorkOrderStatus, MaintenanceType } from "@/lib/types";

// ─────────────────────────────────────────────────────────────────────
// Work Order status badges
// ─────────────────────────────────────────────────────────────────────

export const STATUS_COLORS: Record<string, string> = {
  DRAFT: "bg-gray-100 text-gray-700 border-gray-200",
  PENDING: "bg-amber-100 text-amber-800 border-amber-200",
  IN_PROGRESS: "bg-blue-100 text-blue-800 border-blue-200",
  COMPLETED: "bg-green-100 text-green-800 border-green-200",
  APPROVED: "bg-emerald-100 text-emerald-800 border-emerald-200",
  CANCELLED: "bg-red-100 text-red-700 border-red-200",
};

const STATUS_LABELS: Record<string, string> = {
  DRAFT: "Borrador",
  PENDING: "Pendiente",
  IN_PROGRESS: "En proceso",
  COMPLETED: "Finalizado",
  APPROVED: "Aprobado",
  CANCELLED: "Cancelado",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status;
}

export function StatusBadge({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border bg-background px-2.5 py-0.5 text-xs font-medium",
        STATUS_COLORS[status],
        className
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      {statusLabel(status)}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Maintenance type labels
// ─────────────────────────────────────────────────────────────────────

const MAINTENANCE_TYPE_LABELS: Record<MaintenanceType, string> = {
  PREVENTIVE: "Preventivo",
  CORRECTIVE: "Correctivo",
  PREDICTIVE: "Predictivo",
  PROYECTO: "Proyecto",
  MONTAJE: "Montaje",
  URGENTE: "Urgente",
};

export function maintenanceTypeLabel(type: MaintenanceType): string {
  return MAINTENANCE_TYPE_LABELS[type] || type;
}

export const MAINTENANCE_TYPES: { value: MaintenanceType; label: string }[] =
  Object.entries(MAINTENANCE_TYPE_LABELS).map(([value, label]) => ({
    value: value as MaintenanceType,
    label,
  }));
