"use client";

import { useEffect, useState, use } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft, Loader2, Send, RotateCcw, CheckCircle, XCircle,
  Clock, AlertTriangle, FileText, Eye, Users, Trash2
} from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { signatureImageUrl } from "@/lib/signatures";
import { Shell } from "@/components/layout/shell";
import type { AreaNode, WorkOrderRecord } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { InlineAlert } from "@/components/ui/inline-alert";
import { StatusBadge } from "@/lib/status";
import { SyncBadge, RetrySyncButton } from "@/components/maintenance/sync-badge";
import { cn, formatDateOnly } from "@/lib/utils";
import { PageLoading } from "@/components/ui/page-loading";
import { LOTO_CONTROL_LABELS } from "@/lib/loto";
import { WORK_ORDER_AREAS } from "@/lib/work-order-areas";
import { WorkOrderEvidencePanel } from "@/components/maintenance/work-order-evidence";

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  if (!value) return null;
  return (
    <div className="py-2 border-b border-border last:border-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-sm font-medium">{value}</div>
    </div>
  );
}

type ConfirmAction = "issue" | "return" | "approve" | "cancel" | "reopen" | "reassign";

interface AlertState {
  variant: "success" | "error";
  message: string;
}

export default function OrdenDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [wo, setWo] = useState<WorkOrderRecord | null>(null);
  const [loadingOrder, setLoadingOrder] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<AlertState | null>(null);
  const [showConfirm, setShowConfirm] = useState<ConfirmAction | null>(null);
  const [returnReason, setReturnReason] = useState("");
  const [cancelReason, setCancelReason] = useState("");
  const [reopenReason, setReopenReason] = useState("");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleteReason, setDeleteReason] = useState("");
  const [completionNotes, setCompletionNotes] = useState("");
  // Reasignar — workers disponibles para el selector ({id, full_name}).
  const [assignableUsers, setAssignableUsers] = useState<{ id: number; full_name: string }[]>([]);
  const [reassignResponsible, setReassignResponsible] = useState<number | null>(null);
  const [reassignParticipants, setReassignParticipants] = useState<Set<number>>(new Set());
  const [sections, setSections] = useState<AreaNode[]>([]);
  const [reassignPlantArea, setReassignPlantArea] = useState("");
  const [reassignSectionId, setReassignSectionId] = useState<number | null>(null);
  const [reassignEquipmentId, setReassignEquipmentId] = useState<number | null>(null);

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    loadOrder();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, id]);

  // Carga los trabajadores disponibles para el selector de "Reasignar".
  useEffect(() => {
    if (!user) return;
    api
      .get<{ id: number; full_name: string }[]>("/api/users/workers")
      .then(setAssignableUsers)
      .catch(() => setAssignableUsers([]));
  }, [user]);

  useEffect(() => {
    if (!user || user.role !== "ADMIN") return;
    api.getCached<AreaNode[]>("/api/catalogs/tree", 5 * 60 * 1000)
      .then(setSections)
      .catch(() => setSections([]));
  }, [user]);

  async function loadOrder(silent = false) {
    if (!silent) setLoadingOrder(true);
    setError(null);
    try {
      const data = await api.get<WorkOrderRecord>(`/api/work-orders/${id}`);
      setWo(data);
    } catch {
      if (!silent) setError("No se pudo cargar la orden de trabajo");
    } finally {
      if (!silent) setLoadingOrder(false);
    }
  }

  // Poll mientras la creación asíncrona de Google esté en curso (PENDING),
  // para que el badge de sincronización pase solo a SYNCED/FAILED.
  useEffect(() => {
    if (!user) return;
    const statuses = wo ? [wo.ot_sheet_sync_status, wo.monthly_sheet_sync_status] : [];
    const anyPending = statuses.includes("PENDING");
    if (!anyPending) return;
    const timer = setInterval(() => loadOrder(true), 2000);
    // Deja de pollear tras ~16s aunque siga PENDING: evita recargas infinitas.
    const stop = setTimeout(() => clearInterval(timer), 16000);
    return () => {
      clearInterval(timer);
      clearTimeout(stop);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, wo?.ot_sheet_sync_status, wo?.monthly_sheet_sync_status]);

  const [retrying, setRetrying] = useState(false);
  async function handleRetrySync() {
    setRetrying(true);
    try {
      await api.post(`/api/work-orders/${id}/sync-google`);
      await loadOrder();
      toast("success", "Sincronización completada.");
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "No se pudo sincronizar con Google");
    } finally {
      setRetrying(false);
    }
  }

  function toast(variant: AlertState["variant"], message: string) {
    setNotice({ variant, message });
  }

  async function handleIssue() {
    setActionLoading(true);
    try {
      const updated = await api.post<WorkOrderRecord>(`/api/work-orders/${id}/issue`);
      setWo(updated);
      setShowConfirm(null);
      toast("success", "OT emitida correctamente.");
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "Error al emitir la OT");
    } finally {
      setActionLoading(false);
      setCompletionNotes("");
    }
  }

  async function handleReturn() {
    if (!returnReason.trim()) {
      toast("error", "El motivo de devolución es obligatorio");
      return;
    }
    setActionLoading(true);
    try {
      const updated = await api.post<WorkOrderRecord>(`/api/work-orders/${id}/return`, { return_reason: returnReason.trim() });
      setWo(updated);
      setShowConfirm(null);
      setReturnReason("");
      toast("success", "OT devuelta a En proceso.");
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "Error al devolver la OT");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleApprove() {
    setActionLoading(true);
    try {
      const updated = await api.post<WorkOrderRecord>(`/api/work-orders/${id}/approve`);
      setWo(updated);
      setShowConfirm(null);
      toast("success", "OT aprobada y cerrada.");
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "Error al aprobar la OT");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleCancel() {
    if (!cancelReason.trim()) {
      toast("error", "El motivo de cancelación es obligatorio");
      return;
    }
    setActionLoading(true);
    try {
      const updated = await api.post<WorkOrderRecord>(`/api/work-orders/${id}/cancel`, { cancellation_reason: cancelReason.trim() });
      setWo(updated);
      setShowConfirm(null);
      setCancelReason("");
      toast("success", "OT cancelada.");
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "Error al cancelar la OT");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleReopen() {
    if (!reopenReason.trim()) {
      toast("error", "El motivo de la reapertura es obligatorio");
      return;
    }
    setActionLoading(true);
    try {
      const updated = await api.post<WorkOrderRecord>(`/api/work-orders/${id}/reopen`, { reopen_reason: reopenReason.trim() });
      setWo(updated);
      setShowConfirm(null);
      setReopenReason("");
      toast("success", "OT reabierta correctamente.");
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "Error al reabrir la OT");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleDeleteWorkOrder() {
    if (!wo || deleteConfirmation.trim() !== wo.ot_number || deleteReason.trim().length < 8) return;
    setActionLoading(true);
    try {
      await api.del(`/api/work-orders/${id}`, {
        confirm_ot_number: deleteConfirmation.trim(),
        reason: deleteReason.trim(),
      });
      api.invalidateCache("/api/work-orders");
      api.invalidateCache("/api/work-orders/counter");
      router.replace("/ordenes");
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "No se pudo eliminar la OT");
    } finally {
      setActionLoading(false);
    }
  }

  // ── Reasignar responsable/participantes ────────────────────────────────
  function openReassign() {
    if (!wo) return;
    setReassignResponsible(wo.responsible_user_id);
    setReassignParticipants(
      new Set(
        wo.responsible_user_id != null
          ? [...(wo.participant_user_ids || []), wo.responsible_user_id]
          : wo.participant_user_ids || []
      )
    );
    setReassignPlantArea(wo.plant_area || "");
    setReassignSectionId(wo.area_id || null);
    setReassignEquipmentId(wo.equipment_id || null);
    setShowConfirm("reassign");
  }

  function toggleReassignParticipant(uid: number) {
    setReassignParticipants((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });
  }

  async function handleReassign() {
    if (!wo) return;
    if (reassignResponsible == null) {
      toast("error", "Debe elegir un responsable");
      return;
    }
    if (wo.submitted_for_review && (!reassignPlantArea || !reassignSectionId || !reassignEquipmentId)) {
      toast("error", "Completa área, sección y equipo antes de aceptar la solicitud.");
      return;
    }
    setActionLoading(true);
    try {
      const updated = await api.post<WorkOrderRecord>(`/api/work-orders/${id}/reassign`, {
        responsible_user_id: reassignResponsible,
        participant_user_ids: Array.from(reassignParticipants),
        ...(wo.submitted_for_review ? {
          plant_area: reassignPlantArea,
          area_id: reassignSectionId,
          equipment_id: reassignEquipmentId,
        } : {}),
      });
      setWo(updated);
      setShowConfirm(null);
      toast("success", "OT reasignada correctamente.");
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "Error al reasignar la OT");
    } finally {
      setActionLoading(false);
    }
  }

  if (loading || !user) {
    return <PageLoading message={loading ? "Validando sesión..." : "Redirigiendo al inicio de sesión..."} />;
  }

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      {/* Back button */}
      <Link href="/ordenes" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-4">
        <ArrowLeft className="h-4 w-4" /> Órdenes
      </Link>

      {loadingOrder ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
        </div>
      ) : error || !wo ? (
        <Card>
          <CardContent className="p-6 text-center text-sm text-destructive">
            {error || "Orden no encontrada"}
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Header */}
          <div className="mb-4">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-mono text-lg font-bold text-primary">{wo.ot_number}</span>
              <StatusBadge status={wo.status} />
              {wo.submitted_for_review && (
                <span className="inline-flex items-center rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800">
                  Pendiente de revisión del administrador
                </span>
              )}
              {wo.google_ot_url && (
                <a
                  href={wo.google_ot_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
                >
                  <FileText className="h-3.5 w-3.5" /> Ver en Drive
                </a>
              )}
            </div>
            <h1 className="mt-1 text-xl font-bold">{wo.title}</h1>
          </div>

          {/* Notice / error inline */}
          {notice && (
            <InlineAlert
              variant={notice.variant}
              className="mb-4"
              onDismiss={() => setNotice(null)}
            >
              {notice.message}
            </InlineAlert>
          )}

          {/* Status banners */}
          {wo.status === "COMPLETED" && (
            <div className="mb-4 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-800">
              <CheckCircle className="inline h-4 w-4 mr-1" />
              OT finalizada por {wo.completed_by_name || "el trabajador"}. Pendiente de revisión.
              {wo.actual_duration_minutes != null && (
                <> Duración real: <strong>{wo.actual_duration_minutes} min</strong></>
              )}
            </div>
          )}
          {wo.status === "APPROVED" && (
            <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
              <CheckCircle className="inline h-4 w-4 mr-1" />
              OT aprobada por {wo.approved_by_user_name || "admin"}.
              {wo.approved_at && <> el {new Date(wo.approved_at).toLocaleString("es-CL")}</>}
            </div>
          )}
          {wo.status === "CANCELLED" && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              <XCircle className="inline h-4 w-4 mr-1" />
              OT cancelada.
              {wo.cancellation_reason && <> Motivo: {wo.cancellation_reason}</>}
            </div>
          )}
          {wo.submitted_for_review && user.role === "ADMIN" && (
            <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              Esta OT fue enviada por el supervisor. Asigna el responsable y los participantes para poder aceptarla y emitirla.
            </div>
          )}

          {/* Info card */}
          <Card className="mb-4">
            <CardContent className="p-4">
              <InfoRow label="N° OT" value={wo.ot_number} />
              <InfoRow label="Equipo" value={wo.equipment_name} />
              <InfoRow label="Área" value={wo.area_name} />
              <InfoRow label="Sección" value={wo.section_name} />
              <InfoRow label="Tipo de mantenimiento" value={wo.maintenance_type} />
              <InfoRow
                label="Controles LOTO / AST"
                value={(wo.loto_controls || []).map((control) => LOTO_CONTROL_LABELS[control]).join(", ")}
              />
              <InfoRow label="LOTO" value={wo.loto_status === "YES" ? "Sí" : wo.loto_status === "NO" ? "No" : "N/A"} />
              <InfoRow label="Fecha de solicitud" value={formatDateOnly(wo.request_date)} />
              <InfoRow
                label="Fecha de ejecución"
                value={formatDateOnly(wo.execution_date)}
              />
              <InfoRow
                label="Fecha programada"
                value={formatDateOnly(wo.scheduled_date)}
              />
              <InfoRow
                label="Fecha límite"
                value={
                  wo.due_date ? (
                    <span className={cn(
                      new Date(wo.due_date) < new Date() && (wo.status === "PENDING" || wo.status === "IN_PROGRESS")
                        ? "text-red-600 font-bold"
                        : ""
                    )}>
                      {formatDateOnly(wo.due_date)}
                      {new Date(wo.due_date) < new Date() && (wo.status === "PENDING" || wo.status === "IN_PROGRESS") && " (vencida)"}
                    </span>
                  ) : null
                }
              />
              <InfoRow label="Tiempo estimado" value={wo.estimated_time ? `${wo.estimated_time} minutos` : null} />
              <InfoRow
                label="Responsable"
                value={wo.responsible_user_name || <span className="text-orange-600 font-medium">No asignado</span>}
              />
              {wo.participant_names.length > 0 && (
                <InfoRow label="Participantes" value={wo.participant_names.join(", ")} />
              )}
              <InfoRow label="Solicitado por" value={wo.requested_by} />
              <InfoRow label="Trabajo" value={wo.description || wo.title} />
              <InfoRow label="Recursos requeridos" value={wo.resources_required} />
              <InfoRow label="Riesgos" value={wo.risks} />
              <InfoRow label="Observaciones" value={wo.observations} />
              <InfoRow label="N° vale" value={wo.voucher_number} />
              <InfoRow label="Creado por" value={wo.created_by_name} />
              <InfoRow label="Creado el" value={wo.created_at ? new Date(wo.created_at).toLocaleString("es-CL") : null} />
            </CardContent>
          </Card>

          <WorkOrderEvidencePanel
            woId={wo.id}
            stage={wo.status === "IN_PROGRESS" ? "WORK" : "ISSUE"}
            currentUserId={user.id}
            canUpload={
              (user.role === "ADMIN" || user.role === "SUPERVISOR") &&
              (wo.status === "DRAFT" || wo.status === "PENDING" || wo.status === "IN_PROGRESS")
            }
          />

          {/* Lifecycle card */}
          {(wo.started_at || wo.completed_at || wo.work_time_mode || wo.actual_duration_minutes != null) && (
            <Card className="mb-4">
              <CardContent className="p-4">
                <h3 className="text-sm font-semibold mb-2">Ejecución</h3>
                {wo.started_at && (
                  <InfoRow
                    label="Inicio"
                    value={`${new Date(wo.started_at).toLocaleString("es-CL")}${wo.started_by_name ? ` — por ${wo.started_by_name}` : ""}`}
                  />
                )}
                {wo.completed_at && (
                  <InfoRow
                    label="Finalización"
                    value={`${new Date(wo.completed_at).toLocaleString("es-CL")}${wo.completed_by_name ? ` — por ${wo.completed_by_name}` : ""}`}
                  />
                )}
                {wo.work_time_mode === "RANGE" && (wo.work_start_time || wo.work_end_time) && (
                  <InfoRow
                    label="Horario declarado"
                    value={`${(wo.work_start_time || "").slice(0, 5)} a ${(wo.work_end_time || "").slice(0, 5)}`}
                  />
                )}
                {wo.work_time_mode === "MANUAL" && wo.worked_duration_minutes != null && (
                  <InfoRow label="DuraciÃ³n manual" value={`${wo.worked_duration_minutes} minutos`} />
                )}
                {wo.actual_duration_minutes != null && (
                  <InfoRow label="Horas declaradas por trabajador" value={`${wo.actual_duration_minutes} minutos`} />
                )}
                {wo.completion_notes && <InfoRow label="Notas de finalización" value={wo.completion_notes} />}
              </CardContent>
            </Card>
          )}

          {/* Return reason */}
          {wo.return_reason && (
            <Card className="mb-4 border-orange-200">
              <CardContent className="p-4">
                <h3 className="text-sm font-semibold text-orange-800 mb-1">Devolución</h3>
                <p className="text-sm text-orange-700">{wo.return_reason}</p>
                {wo.returned_at && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Devuelta el {new Date(wo.returned_at).toLocaleString("es-CL")}
                  </p>
                )}
              </CardContent>
            </Card>
          )}

          {/* Sync status */}
          <Card className="mb-4">
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-semibold">Sincronización Google</h3>
                {wo.ot_sheet_sync_status === "PENDING" || wo.monthly_sheet_sync_status === "PENDING" ? (
                  <Loader2 className="h-4 w-4 animate-spin text-amber-600" />
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <span className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">OT:</span>
                  <SyncBadge status={wo.ot_sheet_sync_status} />
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">Mensual:</span>
                  <SyncBadge status={wo.monthly_sheet_sync_status} />
                </span>
                {(wo.ot_sheet_sync_status === "FAILED" || wo.monthly_sheet_sync_status === "FAILED") && (
                  <RetrySyncButton onRetry={handleRetrySync} loading={retrying} />
                )}
              </div>
              {wo.ot_sheet_sync_error && (
                <p className="text-xs text-red-600 mt-1">Error OT: {wo.ot_sheet_sync_error}</p>
              )}
              {wo.monthly_sheet_sync_error && (
                <p className="text-xs text-red-600 mt-1">Error mensual: {wo.monthly_sheet_sync_error}</p>
              )}
            </CardContent>
          </Card>

          {/* ── Action Buttons ─────────────────────────────────────────── */}
          {!showConfirm && wo.status === "DRAFT" && (
            <div className="flex gap-2">
              <Link href={`/ordenes/nuevo?edit=${wo.id}`} className="flex-1">
                <Button variant="outline" className="w-full">
                  <Eye className="mr-1 h-4 w-4" /> Editar
                </Button>
              </Link>
              {(!wo.submitted_for_review || user.role === "ADMIN") && (
                <Button className="flex-1" onClick={() => setShowConfirm("issue")}>
                  <Send className="mr-1 h-4 w-4" /> {wo.submitted_for_review ? "Aceptar y emitir" : user.role === "SUPERVISOR" ? "Enviar al administrador" : "Emitir OT"}
                </Button>
              )}
            </div>
          )}

          {!showConfirm && wo.status === "COMPLETED" && user.role === "ADMIN" && (
            <div className="flex gap-2">
              <Button variant="outline" className="flex-1" onClick={() => setShowConfirm("return")}>
                <RotateCcw className="mr-1 h-4 w-4" /> Devolver
              </Button>
              <Button className="flex-1" onClick={() => setShowConfirm("approve")}>
                <CheckCircle className="mr-1 h-4 w-4" /> Aprobar
              </Button>
            </div>
          )}

          {!showConfirm && (wo.status === "PENDING" || wo.status === "IN_PROGRESS") && (
            <Button variant="destructive" className="w-full" onClick={() => setShowConfirm("cancel")}>
              <XCircle className="mr-1 h-4 w-4" /> Cancelar OT
            </Button>
          )}

          {/* Reasignar — solo managers, en estados activos (no terminales) */}
          {!showConfirm &&
            user.role === "ADMIN" &&
            (wo.status === "DRAFT" || wo.status === "PENDING" || wo.status === "IN_PROGRESS") && (
              <Button
                variant="outline"
                className="mt-2 w-full"
                onClick={openReassign}
              >
                <Users className="mr-1 h-4 w-4" /> Reasignar responsable
              </Button>
            )}

          {!showConfirm && (wo.status === "APPROVED" || wo.status === "CANCELLED") && user.role === "ADMIN" && (
            <Button
              variant="outline"
              className="w-full border-orange-300 text-orange-700 hover:bg-orange-50"
              onClick={() => setShowConfirm("reopen")}
            >
              <RotateCcw className="mr-1 h-4 w-4" /> Reabrir OT
            </Button>
          )}

          {/* ── Confirmations (unificadas con ConfirmDialog) ─────────── */}
          {user.role === "ADMIN" && (
            <Card className="mt-5 border-red-200">
              <CardContent className="p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="font-semibold text-red-800">Zona de peligro</h3>
                    <p className="text-sm text-muted-foreground">
                      Elimina esta OT de la aplicación y del registro mensual; su documento de Drive irá a la papelera.
                    </p>
                  </div>
                  {!showDeleteConfirm && (
                    <Button
                      variant="destructive"
                      onClick={() => {
                        setShowConfirm(null);
                        setShowDeleteConfirm(true);
                      }}
                    >
                      <Trash2 className="mr-2 h-4 w-4" /> Eliminar OT
                    </Button>
                  )}
                </div>
                {showDeleteConfirm && (
                  <ConfirmDialog
                    title={`Eliminar ${wo.ot_number} y sus registros`}
                    description={
                      <>
                        Se quitará de la aplicación y del registro mensual, y el archivo de Drive se moverá a la papelera.
                        Las notificaciones dentro de la app se borrarán; los correos ya enviados no se pueden retirar.
                        Se conservará una auditoría mínima del borrado. Esta acción no se puede deshacer desde la app.
                      </>
                    }
                    confirmLabel="Eliminar OT y registros"
                    tone="destructive"
                    busy={actionLoading}
                    disabled={
                      deleteConfirmation.trim() !== wo.ot_number ||
                      deleteReason.trim().length < 8
                    }
                    onConfirm={handleDeleteWorkOrder}
                    onCancel={() => {
                      setShowDeleteConfirm(false);
                      setDeleteConfirmation("");
                      setDeleteReason("");
                    }}
                  >
                    <div className="mb-3 space-y-3">
                      <label className="block text-sm font-medium">
                        Escribe exactamente <span className="font-mono">{wo.ot_number}</span>
                        <input
                          className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm"
                          value={deleteConfirmation}
                          onChange={(event) => setDeleteConfirmation(event.target.value)}
                          autoComplete="off"
                        />
                      </label>
                      <label className="block text-sm font-medium">
                        Motivo del borrado (mínimo 8 caracteres)
                        <textarea
                          className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                          rows={2}
                          value={deleteReason}
                          onChange={(event) => setDeleteReason(event.target.value)}
                          placeholder="Ej.: OT creada por error"
                        />
                      </label>
                    </div>
                  </ConfirmDialog>
                )}
              </CardContent>
            </Card>
          )}

          {showConfirm === "issue" && (
            <ConfirmDialog
              title="¿Emitir esta OT?"
              description={
                <>
                  La OT pasará a <strong>Pendiente</strong>. Se creará el archivo en Google Drive y se sincronizará con el mensual.
                </>
              }
              confirmLabel="Sí, emitir"
              busy={actionLoading}
              onConfirm={handleIssue}
              onCancel={() => setShowConfirm(null)}
            />
          )}

          {showConfirm === "return" && (
            <ConfirmDialog
              title="¿Devolver esta OT?"
              description={
                <>
                  La OT volverá a <strong>En proceso</strong> para que el trabajador corrija.
                </>
              }
              confirmLabel="Devolver"
              busy={actionLoading}
              onConfirm={handleReturn}
              onCancel={() => { setShowConfirm(null); setReturnReason(""); }}
              >
              <div className="mb-3">
                <label className="text-sm font-medium">Motivo de devolución (obligatorio)</label>
                <textarea
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  rows={3}
                  placeholder="Describe qué necesita corrección..."
                  value={returnReason}
                  onChange={(e) => setReturnReason(e.target.value)}
                />
              </div>
            </ConfirmDialog>
          )}

          {showConfirm === "approve" && (
            <ConfirmDialog
              title="¿Aprobar esta OT?"
              description={
                <>
                  La OT pasará a <strong>Aprobada</strong> (estado terminal). Se sincronizará con el mensual como APROBADA.
                </>
              }
              confirmLabel="Aprobar"
              tone="success"
              busy={actionLoading}
              disabled={!user.signature}
              onConfirm={handleApprove}
              onCancel={() => setShowConfirm(null)}
            >
              {user.signature ? (
                <div className="mb-3 rounded-md border bg-white p-2">
                  <p className="mb-2 text-xs text-muted-foreground">Se aplicará su firma manuscrita guardada.</p>
                  <img src={signatureImageUrl(user.signature)} alt="Su firma" className="h-14 w-full object-contain" />
                </div>
              ) : (
                <InlineAlert variant="warning" className="mb-3">
                  Debe cargar su firma en <Link href="/perfil" className="font-medium underline">Mi firma</Link> antes de aprobar.
                </InlineAlert>
              )}
            </ConfirmDialog>
          )}

          {showConfirm === "cancel" && (
            <ConfirmDialog
              title="¿Cancelar esta OT?"
              description={
                <>
                  La OT pasará a <strong>Cancelada</strong> (estado terminal). Esta acción no se puede deshacer.
                </>
              }
              confirmLabel="Cancelar OT"
              tone="destructive"
              busy={actionLoading}
              onConfirm={handleCancel}
              onCancel={() => { setShowConfirm(null); setCancelReason(""); }}
            >
              <div className="mb-3">
                <label className="text-sm font-medium">Motivo de cancelación (obligatorio)</label>
                <textarea
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  rows={3}
                  placeholder="Describe el motivo de cancelación..."
                  value={cancelReason}
                  onChange={(e) => setCancelReason(e.target.value)}
                />
              </div>
            </ConfirmDialog>
          )}

          {showConfirm === "reopen" && (
            <ConfirmDialog
              title="¿Reabrir esta OT?"
              description={
                wo.status === "APPROVED" ? (
                  <>La OT pasará a <strong>En proceso</strong> para que el trabajador continúe (reabierta por admin).</>
                ) : (
                  <>La OT pasará a <strong>Borrador</strong> para re-planificarla y re-emitirla.</>
                )
              }
              confirmLabel="Reabrir OT"
              tone="success"
              busy={actionLoading}
              onConfirm={handleReopen}
              onCancel={() => { setShowConfirm(null); setReopenReason(""); }}
            >
              <div className="mb-3">
                <label className="text-sm font-medium">Motivo de la reapertura (obligatorio)</label>
                <textarea
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  rows={3}
                  placeholder="Describe el motivo de la reapertura..."
                  value={reopenReason}
                  onChange={(e) => setReopenReason(e.target.value)}
                />
              </div>
            </ConfirmDialog>
          )}

          {showConfirm === "reassign" && (
            <ConfirmDialog
              title="Reasignar responsable y participantes"
              description={
                <>
                  Esta OT actualmente tiene como responsable a{" "}
                  <strong>{wo.responsible_user_name || "nadie"}</strong>. Elija el
                  nuevo responsable y los participantes. Se les notificará.
                </>
              }
              confirmLabel="Reasignar"
              busy={actionLoading}
              onConfirm={handleReassign}
              onCancel={() => setShowConfirm(null)}
            >
              {wo.submitted_for_review && (
                <div className="mb-4 rounded-md border bg-muted/20 p-3">
                  <p className="mb-2 text-sm font-semibold">Revisar área y equipo</p>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <label className="text-sm">
                      Área
                      <select className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2" value={reassignPlantArea} onChange={(e) => setReassignPlantArea(e.target.value)}>
                        <option value="">Seleccionar...</option>
                        {WORK_ORDER_AREAS.map((name) => <option key={name} value={name}>{name}</option>)}
                      </select>
                    </label>
                    <label className="text-sm">
                      Sección
                      <select className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2" value={reassignSectionId ?? ""} onChange={(e) => { setReassignSectionId(e.target.value ? Number(e.target.value) : null); setReassignEquipmentId(null); }}>
                        <option value="">Seleccionar...</option>
                        {sections.map((section) => <option key={section.id} value={section.id}>{section.name}</option>)}
                      </select>
                    </label>
                    <label className="text-sm">
                      Equipo
                      <select className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2" value={reassignEquipmentId ?? ""} disabled={!reassignSectionId} onChange={(e) => setReassignEquipmentId(e.target.value ? Number(e.target.value) : null)}>
                        <option value="">Seleccionar...</option>
                        {(sections.find((section) => section.id === reassignSectionId)?.equipment || []).map((equipment) => <option key={equipment.id} value={equipment.id}>{equipment.name}</option>)}
                      </select>
                    </label>
                  </div>
                </div>
              )}
              <div className="mb-3">
                <label className="text-sm font-medium">Responsable</label>
                <select
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={reassignResponsible ?? ""}
                  onChange={(e) => {
                    const id = e.target.value ? Number(e.target.value) : null;
                    setReassignResponsible(id);
                    if (id != null) {
                      setReassignParticipants((previous) => {
                        const next = new Set(previous);
                        next.add(id);
                        return next;
                      });
                    }
                  }}
                >
                  <option value="">Seleccionar...</option>
                  {assignableUsers.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="mb-3">
                <label className="text-sm font-medium">Participantes</label>
                <p className="mt-1 text-xs text-muted-foreground">
                  El responsable se agrega automáticamente como participante.
                </p>
                <div className="mt-1 grid gap-1.5">
                  {assignableUsers.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No hay trabajadores disponibles</p>
                  ) : (
                    assignableUsers.map((u) => (
                      <label key={u.id} className="inline-flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={reassignParticipants.has(u.id)}
                          disabled={reassignResponsible === u.id}
                          onChange={() => toggleReassignParticipant(u.id)}
                          className="h-4 w-4 rounded border-input"
                        />
                        {u.full_name}
                      </label>
                    ))
                  )}
                </div>
              </div>
            </ConfirmDialog>
          )}
        </>
      )}
    </Shell>
  );
}
