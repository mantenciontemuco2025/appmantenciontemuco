"use client";

import { ChevronDown, Loader2, ScrollText } from "lucide-react";
import { api } from "@/lib/api";
import type { AuditLogEntry } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { InlineAlert } from "@/components/ui/inline-alert";
import { usePagination } from "@/lib/use-pagination";

const ACTION_STYLES: Record<string, string> = {
  CREATE: "text-emerald-700 bg-emerald-50 border-emerald-200",
  UPDATE: "text-blue-700 bg-blue-50 border-blue-200",
  DELETE: "text-red-700 bg-red-50 border-red-200",
  LOGIN: "text-slate-700 bg-slate-50 border-slate-200",
  SYNC_GOOGLE_SHEETS: "text-amber-700 bg-amber-50 border-amber-200",
  ISSUE_WORK_ORDER: "text-blue-700 bg-blue-50 border-blue-200",
  START_WORK_ORDER: "text-blue-700 bg-blue-50 border-blue-200",
  COMPLETE_WORK_ORDER: "text-green-700 bg-green-50 border-green-200",
  RETURN_WORK_ORDER: "text-orange-700 bg-orange-50 border-orange-200",
  APPROVE_WORK_ORDER: "text-emerald-700 bg-emerald-50 border-emerald-200",
  CANCEL_WORK_ORDER: "text-red-700 bg-red-50 border-red-200",
  REOPEN_WORK_ORDER: "text-amber-700 bg-amber-50 border-amber-200",
};

function actionStyle(action: string): string {
  return ACTION_STYLES[action] || "text-slate-700 bg-slate-50 border-slate-200";
}

function actionLabel(action: string): string {
  const map: Record<string, string> = {
    CREATE: "Creación",
    UPDATE: "Actualización",
    DELETE: "Eliminación",
    LOGIN: "Inicio de sesión",
    SYNC_GOOGLE_SHEETS: "Sync Google",
    ISSUE_WORK_ORDER: "Emisión OT",
    START_WORK_ORDER: "Inicio OT",
    COMPLETE_WORK_ORDER: "Finalización OT",
    RETURN_WORK_ORDER: "Devolución OT",
    APPROVE_WORK_ORDER: "Aprobación OT",
    CANCEL_WORK_ORDER: "Cancelación OT",
    REOPEN_WORK_ORDER: "Reapertura OT",
  };
  return map[action] || action.replace(/_/g, " ").toLowerCase();
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Sí" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Traduce nombres de campo a etiquetas legibles. */
function fieldLabel(key: string): string {
  const map: Record<string, string> = {
    status: "Estado",
    ot_number: "N° OT",
    title: "Título",
    area_id: "Área",
    equipment_id: "Equipo",
    responsible_user_id: "Responsable",
    is_planned: "Planificada",
    due_date: "Fecha límite",
    scheduled_date: "Fecha programada",
    execution_date: "Fecha ejecución",
    request_date: "Fecha solicitud",
    maintenance_type: "Tipo",
    loto_status: "LOTO",
    full_name: "Nombre",
    email: "Email",
    role: "Rol",
    is_active: "Activo",
    description: "Descripción",
    section_name: "Sección",
    estimated_time: "Tiempo estimado",
    resources_required: "Recursos",
    risks: "Riesgos",
    observations: "Observaciones",
    folio: "Folio",
    voucher_number: "N° vale",
    approved_by: "Aprobado por",
    requested_by: "Solicitado por",
    participant_names: "Participantes",
    completion_notes: "Notas de finalización",
    return_reason: "Motivo de devolución",
    cancellation_reason: "Motivo de cancelación",
    reopen_reason: "Motivo de reapertura",
  };
  return map[key] || key;
}

const PAGE_SIZE = 30;

export function AuditLogView() {
  const { items: logs, loading, loadingMore, hasMore, error, loadMore } =
    usePagination<AuditLogEntry>({
      fetcher: (_offset, n) => api.get<AuditLogEntry[]>(`/api/audit?limit=${n}&offset=${_offset}`),
      pageSize: PAGE_SIZE,
    });

  if (loading) {
    return (
      <div className="flex justify-center py-10">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  if (error) {
    return (
      <InlineAlert variant="error" className="mb-3">
        {error}
      </InlineAlert>
    );
  }

  if (logs.length === 0) {
    return (
      <EmptyState
        icon={<ScrollText className="h-6 w-6" />}
        title="Sin registros de auditoría"
        description="Las acciones del sistema aparecerán aquí."
      />
    );
  }

  return (
    <>
      <ul className="space-y-2">
        {logs.map((l) => (
          <li key={l.id} className="rounded-lg border bg-card p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-muted-foreground">
                  {l.user.full_name.slice(0, 1).toUpperCase()}
                </span>
                <span className="font-medium truncate">{l.user.full_name}</span>
              </div>
              <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${actionStyle(l.action)}`}>
                {actionLabel(l.action)}
              </span>
            </div>
            <div className="mt-1 text-sm text-muted-foreground">
              {l.entity_type} {l.entity_id ? `#${l.entity_id}` : ""}
            </div>

            {/* Cambios legibles (prev → new) */}
            {l.new_data && Object.keys(l.new_data).length > 0 && (
              <div className="mt-2 overflow-hidden rounded-md border">
                <div className="grid grid-cols-[1fr_auto_1fr] gap-1 bg-muted/40 px-2 py-1 text-xs font-semibold">
                  <span>Campo</span>
                  <span />
                  <span>Valor</span>
                </div>
                {Object.entries(l.new_data).map(([k, v]) => {
                  const prev = l.previous_data?.[k];
                  return (
                    <div key={k} className="grid grid-cols-[1fr_auto_1fr] items-center gap-1 border-t border-border px-2 py-1 text-xs">
                      <span className="text-muted-foreground truncate">{fieldLabel(k)}</span>
                      {prev !== undefined && prev !== v ? (
                        <span className="text-[10px] font-semibold text-amber-600">→</span>
                      ) : (
                        <span />
                      )}
                      <span
                        className={
                          prev !== undefined && prev !== v
                            ? "font-medium text-emerald-700"
                            : "text-foreground"
                        }
                      >
                        {formatValue(v)}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="mt-1 text-xs text-muted-foreground">
              {new Date(l.created_at).toLocaleString("es-CL")}
            </div>
          </li>
        ))}
      </ul>

      {/* Footer — contador + Cargar más */}
      <div className="mt-4 flex flex-col items-center gap-3">
        <p className="text-xs text-muted-foreground">
          Mostrando {logs.length} registro{logs.length === 1 ? "" : "s"} (recientes primero)
        </p>
        {hasMore && (
          <Button variant="outline" onClick={loadMore} disabled={loadingMore} className="w-full sm:w-auto">
            {loadingMore ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <ChevronDown className="mr-2 h-4 w-4" />
            )}
            Cargar más
          </Button>
        )}
        {!hasMore && (
          <p className="text-xs text-muted-foreground">Fin de la lista</p>
        )}
      </div>
    </>
  );
}