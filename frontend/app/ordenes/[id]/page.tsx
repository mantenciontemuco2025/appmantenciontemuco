"use client";

import { createContext, useContext, useEffect, useState, use } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft, Loader2, Send, RotateCcw, CheckCircle, XCircle,
  Clock, AlertTriangle, FileText, Eye, Users, Trash2, Pencil, X
} from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { signatureImageUrl } from "@/lib/signatures";
import { Shell } from "@/components/layout/shell";
import type { AreaNode, LotoControl, WorkOrderRecord, WorkTimeMode } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { InlineAlert } from "@/components/ui/inline-alert";
import { MAINTENANCE_TYPES, StatusBadge } from "@/lib/status";
import { SyncBadge, RetrySyncButton } from "@/components/maintenance/sync-badge";
import { cn, formatDateOnly } from "@/lib/utils";
import { PageLoading } from "@/components/ui/page-loading";
import { LOTO_CONTROL_LABELS, LOTO_CONTROL_OPTIONS } from "@/lib/loto";
import { WORK_ORDER_AREAS } from "@/lib/work-order-areas";
import { WorkOrderEvidencePanel } from "@/components/maintenance/work-order-evidence";
import { HallazgoReviewPanel } from "@/components/orders/hallazgo-review-panel";
import { HallazgoEditPanel } from "@/components/orders/hallazgo-edit-panel";

interface InfoRowEditContextValue {
  canEdit: boolean;
  editingField: string | null;
  fieldForLabel: (label: string) => string | null;
  renderEditor: (field: string) => React.ReactNode;
  onEdit: (field: string) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
}

const InfoRowEditContext = createContext<InfoRowEditContextValue | null>(null);

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  const edit = useContext(InfoRowEditContext);
  if (label === "LOTO") return null;
  const field = edit?.canEdit ? edit.fieldForLabel(label) : null;
  if (!value && !field) return null;
  if (edit?.canEdit && field) {
    const editing = edit.editingField === field;
    return (
      <div className="relative border-b border-border py-2 last:border-0">
        <div className="text-xs text-muted-foreground">{label}</div>
        {editing ? (
          <div className="mt-1 space-y-2">
            {edit.renderEditor(field)}
            <div className="flex gap-2">
              <Button type="button" size="sm" onClick={edit.onSave} disabled={edit.saving}>Guardar</Button>
              <Button type="button" size="sm" variant="outline" onClick={edit.onCancel} disabled={edit.saving}>Cancelar</Button>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm font-medium">{value || "—"}</div>
            <Button type="button" variant="ghost" size="sm" className="shrink-0 text-primary" onClick={() => edit.onEdit(field)} aria-label={`Editar ${label}`}>
              <Pencil className="mr-1 h-3.5 w-3.5" /> Editar
            </Button>
          </div>
        )}
      </div>
    );
  }
  return (
    <div className="py-2 border-b border-border last:border-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-sm font-medium">{value}</div>
    </div>
  );
}

type ConfirmAction = "issue" | "return" | "approve" | "cancel" | "reopen" | "reassign" | "external" | "internal";
type SupervisorReviewAction = "CLAIM" | "APPROVE" | "RETURN";

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
  const [supervisorReviewNotes, setSupervisorReviewNotes] = useState("");
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
  const [externalExecutorName, setExternalExecutorName] = useState("");
  const [externalCompany, setExternalCompany] = useState("");
  const [adminEdit, setAdminEdit] = useState({
    description: "",
    plant_area: "",
    area_id: null as number | null,
    equipment_id: null as number | null,
    section_name: "",
    maintenance_type: "PREVENTIVE" as WorkOrderRecord["maintenance_type"],
    loto_status: "NOT_APPLICABLE" as WorkOrderRecord["loto_status"],
    loto_controls: [] as LotoControl[],
    execution_date: "",
    estimated_time: "",
    folio: "",
    voucher_number: "",
    voucher_date: "",
    material_codes: "",
    resources_required: "",
    risks: "",
    observations: "",
    work_time_mode: "RANGE" as WorkTimeMode,
    work_start_time: "",
    work_end_time: "",
    manual_hours: "",
    manual_minutes: "",
  });
  const [savingAdminEdit, setSavingAdminEdit] = useState(false);
  const [showAdminEdit, setShowAdminEdit] = useState(false);
  const [inlineEditField, setInlineEditField] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    loadOrder();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, id]);

  useEffect(() => {
    if (!wo) return;
    setAdminEdit({
      description: wo.description || "",
      plant_area: wo.plant_area || "",
      area_id: wo.area_id,
      equipment_id: wo.equipment_id,
      section_name: wo.section_name || "",
      maintenance_type: wo.maintenance_type || "PREVENTIVE",
      loto_status: wo.loto_status || "NOT_APPLICABLE",
      loto_controls: wo.loto_controls || [],
      execution_date: (wo.execution_date || "").slice(0, 10),
      estimated_time: wo.estimated_time || "",
      folio: wo.folio || "",
      voucher_number: wo.voucher_number || "",
      voucher_date: (wo.voucher_date || "").slice(0, 10),
      material_codes: wo.material_codes || "",
      resources_required: wo.resources_required || "",
      risks: wo.risks || "",
      observations: wo.observations || "",
      work_time_mode:
        wo.work_time_mode || (wo.worked_duration_minutes != null ? "MANUAL" : "RANGE"),
      work_start_time:
        wo.work_time_mode === "RANGE" ? (wo.work_start_time || "").slice(0, 5) : "",
      work_end_time:
        wo.work_time_mode === "RANGE" ? (wo.work_end_time || "").slice(0, 5) : "",
      manual_hours:
        wo.work_time_mode === "MANUAL" && wo.worked_duration_minutes != null
          ? String(Math.floor(wo.worked_duration_minutes / 60))
          : "",
      manual_minutes:
        wo.work_time_mode === "MANUAL" && wo.worked_duration_minutes != null
          ? String(wo.worked_duration_minutes % 60)
          : "",
    });
  }, [wo]);

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

  async function saveAdminEdit() {
    if (!wo || savingAdminEdit) return;

    let workedDuration: number | null = null;
    if (adminEdit.work_time_mode === "RANGE") {
      const hasStart = Boolean(adminEdit.work_start_time);
      const hasEnd = Boolean(adminEdit.work_end_time);
      if (hasStart !== hasEnd) {
        toast("error", "Para usar Desde / hasta debes indicar inicio y término.");
        return;
      }
      if (hasStart && hasEnd) {
        const [startHour, startMinute] = adminEdit.work_start_time.split(":").map(Number);
        const [endHour, endMinute] = adminEdit.work_end_time.split(":").map(Number);
        const start = startHour * 60 + startMinute;
        const end = endHour * 60 + endMinute;
        if (end <= start) {
          toast("error", "La hora de término debe ser posterior a la hora de inicio.");
          return;
        }
        workedDuration = end - start;
      }
    } else {
      const hours = adminEdit.manual_hours === "" ? 0 : Number(adminEdit.manual_hours);
      const minutes = adminEdit.manual_minutes === "" ? 0 : Number(adminEdit.manual_minutes);
      if (!Number.isInteger(hours) || hours < 0 || !Number.isInteger(minutes) || minutes < 0 || minutes > 59) {
        toast("error", "La duración manual debe tener horas enteras y minutos entre 0 y 59.");
        return;
      }
      workedDuration = hours * 60 + minutes;
      if (workedDuration <= 0) {
        toast("error", "Indica una duración manual mayor que cero.");
        return;
      }
    }

    setSavingAdminEdit(true);
    setError(null);
    try {
      const updated = await api.patch<WorkOrderRecord>(`/api/work-orders/${wo.id}`, {
        description: adminEdit.description,
        plant_area: adminEdit.plant_area || null,
        area_id: adminEdit.area_id,
        equipment_id: adminEdit.equipment_id,
        section_name: adminEdit.section_name.trim() || null,
        maintenance_type: adminEdit.maintenance_type,
        loto_status: adminEdit.loto_status,
        loto_controls: adminEdit.loto_controls,
        execution_date: adminEdit.execution_date || null,
        folio: adminEdit.folio || null,
        voucher_number: adminEdit.voucher_number || null,
        voucher_date: adminEdit.voucher_date || null,
        material_codes: adminEdit.material_codes.trim() || null,
        resources_required: adminEdit.resources_required || null,
        risks: adminEdit.risks || null,
        observations: adminEdit.observations || null,
        work_time_mode: adminEdit.work_time_mode,
        work_start_time: adminEdit.work_time_mode === "RANGE" ? adminEdit.work_start_time || null : null,
        work_end_time: adminEdit.work_time_mode === "RANGE" ? adminEdit.work_end_time || null : null,
        worked_duration_minutes: adminEdit.work_time_mode === "MANUAL" ? workedDuration : null,
      });
      setWo(updated);
      setInlineEditField(null);
      toast("success", "Cambios guardados. La OT de Drive se actualizará en segundo plano.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron guardar los cambios");
    } finally {
      setSavingAdminEdit(false);
    }
  }

  const canInlineEdit = user?.role === "ADMIN" && wo?.status === "COMPLETED";
  const officialDurationMinutes = wo?.worked_duration_minutes ?? (
    wo?.actual_duration_minutes != null ? Math.round(wo.actual_duration_minutes) : null
  );

  function editableInfoRow(
    label: string,
    field: string,
    value: React.ReactNode,
    editor: React.ReactNode,
  ) {
    if (!canInlineEdit) return <InfoRow label={label} value={value} />;
    const editing = inlineEditField === field;
    return (
      <div className="relative border-b border-border py-2 last:border-0">
        <div className="text-xs text-muted-foreground">{label}</div>
        {editing ? (
          <div className="mt-1 space-y-2">
            {editor}
            <div className="flex gap-2">
              <Button type="button" size="sm" onClick={() => void saveAdminEdit()} disabled={savingAdminEdit}>
                {savingAdminEdit && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                Guardar
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => setInlineEditField(null)} disabled={savingAdminEdit}>
                Cancelar
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm font-medium">{value || "—"}</div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="shrink-0 text-primary"
              onClick={() => setInlineEditField(field)}
              aria-label={`Editar ${label}`}
            >
              <Pencil className="mr-1 h-3.5 w-3.5" /> Editar
            </Button>
          </div>
        )}
      </div>
    );
  }

  const infoRowEditContext: InfoRowEditContextValue = {
    canEdit: Boolean(canInlineEdit),
    editingField: inlineEditField,
    fieldForLabel: (label) => {
      if (label === "Equipo") return "equipment_id";
      if (label.includes("Controles LOTO")) return "loto_controls";
      if (label.includes("rea")) return "plant_area";
      if (label.includes("Secci")) return "section_name";
      if (label.includes("Fecha de ejec")) return "execution_date";
      if (label.includes("Fecha de vale")) return "voucher_date";
      if (label.includes("vale")) return "voucher_number";
      if (label.includes("digos de materiales")) return "material_codes";
      return null;
    },
    renderEditor: (field) => {
      if (field === "equipment_id") {
        const catalogArea = sections.find((section) => section.id === adminEdit.area_id);
        const equipmentOptions = [...(catalogArea?.equipment || [])];
        if (wo?.equipment_id && !equipmentOptions.some((equipment) => equipment.id === wo.equipment_id)) {
          equipmentOptions.unshift({ id: wo.equipment_id, name: wo.equipment_name || "Equipo actual" });
        }
        return (
          <select
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            value={adminEdit.equipment_id ?? ""}
            onChange={(event) => setAdminEdit((current) => ({ ...current, equipment_id: event.target.value ? Number(event.target.value) : null }))}
          >
            <option value="">Sin equipo especÃ­fico</option>
            {equipmentOptions.map((equipment) => <option key={equipment.id} value={equipment.id}>{equipment.name}</option>)}
          </select>
        );
      }
      if (field === "plant_area") return (
        <select
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={adminEdit.plant_area}
          onChange={(event) => setAdminEdit((current) => ({ ...current, plant_area: event.target.value }))}
        >
          <option value="">Seleccionar Ã¡rea</option>
          {WORK_ORDER_AREAS.map((area) => <option key={area} value={area}>{area}</option>)}
        </select>
      );
      if (field === "loto_status") return (
        <select
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={adminEdit.loto_status}
          onChange={(event) => {
            const status = event.target.value as WorkOrderRecord["loto_status"];
            setAdminEdit((current) => ({
              ...current,
              loto_status: status,
              loto_controls: status === "YES"
                ? (current.loto_controls.length && !current.loto_controls.includes("NOT_APPLICABLE") ? current.loto_controls : ["LOTO_BLOQUEO"])
                : status === "NOT_APPLICABLE" ? ["NOT_APPLICABLE"] : [],
            }));
          }}
        >
          <option value="NOT_APPLICABLE">No aplica</option>
          <option value="YES">SÃ­</option>
          <option value="NO">No</option>
        </select>
      );
      if (field === "loto_controls") return (
        <div className="grid gap-2 sm:grid-cols-2">
          {LOTO_CONTROL_OPTIONS.map((option) => (
            <label key={option.value} className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm">
              <input
                type="checkbox"
                checked={adminEdit.loto_controls.includes(option.value)}
                onChange={(event) => setAdminEdit((current) => {
                  const next = event.target.checked
                    ? [...current.loto_controls.filter((control) => control !== "NOT_APPLICABLE"), option.value]
                    : current.loto_controls.filter((control) => control !== option.value);
                  return { ...current, loto_controls: next, loto_status: next.length ? "YES" : "NO" };
                })}
              />
              {option.label}
            </label>
          ))}
          <label className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm">
            <input
              type="checkbox"
              checked={adminEdit.loto_controls.includes("NOT_APPLICABLE")}
              onChange={(event) => setAdminEdit((current) => ({
                ...current,
                loto_controls: event.target.checked ? ["NOT_APPLICABLE"] : [],
                loto_status: event.target.checked ? "NOT_APPLICABLE" : "NO",
              }))}
            />
            No aplica
          </label>
        </div>
      );
      if (field === "section_name") return (
        <div className="space-y-2">
          <select
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            value={adminEdit.area_id ?? ""}
            onChange={(event) => {
              const areaId = event.target.value ? Number(event.target.value) : null;
              const section = sections.find((item) => item.id === areaId);
              setAdminEdit((current) => ({
                ...current,
                area_id: areaId,
                section_name: section?.name || "",
                equipment_id: null,
              }));
            }}
          >
            <option value="">Seleccionar secciÃ³n</option>
            {sections.map((section) => <option key={section.id} value={section.id}>{section.name}</option>)}
          </select>
          <select
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            value={adminEdit.equipment_id ?? ""}
            onChange={(event) => setAdminEdit((current) => ({ ...current, equipment_id: event.target.value ? Number(event.target.value) : null }))}
            disabled={!adminEdit.area_id}
          >
            <option value="">Seleccionar equipo de la secciÃ³n</option>
            {(sections.find((section) => section.id === adminEdit.area_id)?.equipment || []).map((equipment) => (
              <option key={equipment.id} value={equipment.id}>{equipment.name}</option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground">El equipo debe pertenecer a la secciÃ³n seleccionada.</p>
        </div>
      );
      if (field === "section_name") return (
        <select className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={adminEdit.section_name} onChange={(event) => setAdminEdit((current) => ({ ...current, section_name: event.target.value }))}>
          <option value="">Sin sección</option>
          {sections.map((section) => <option key={section.id} value={section.name}>{section.name}</option>)}
        </select>
      );
      if (field === "execution_date") return <Input type="date" value={adminEdit.execution_date} onChange={(event) => setAdminEdit((current) => ({ ...current, execution_date: event.target.value }))} />;
      if (field === "voucher_date") return <Input type="date" value={adminEdit.voucher_date} onChange={(event) => setAdminEdit((current) => ({ ...current, voucher_date: event.target.value }))} />;
      if (field === "voucher_number") return <Input value={adminEdit.voucher_number} onChange={(event) => setAdminEdit((current) => ({ ...current, voucher_number: event.target.value }))} />;
      if (field === "material_codes") return <Input value={adminEdit.material_codes} onChange={(event) => setAdminEdit((current) => ({ ...current, material_codes: event.target.value }))} placeholder="Código 1-Código 2" />;
      return null;
    },
    onEdit: setInlineEditField,
    onSave: () => void saveAdminEdit(),
    onCancel: () => setInlineEditField(null),
    saving: savingAdminEdit,
  };

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

  async function handleConvertToExternal() {
    if (!externalExecutorName.trim()) {
      toast("error", "Indica el nombre de la persona externa.");
      return;
    }
    setActionLoading(true);
    try {
      const updated = await api.patch<WorkOrderRecord>(`/api/work-orders/${id}`, {
        is_external_work: true,
        external_executor_name: externalExecutorName.trim(),
        external_company: externalCompany.trim() || null,
        responsible_user_id: null,
        participant_user_ids: [],
      });
      setWo(updated);
      setShowConfirm(null);
      setExternalExecutorName("");
      setExternalCompany("");
      toast("success", "La OT quedó configurada como trabajo externo. Ahora puedes aceptarla y emitirla.");
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "No se pudo configurar la OT externa");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleConvertToInternal() {
    setActionLoading(true);
    try {
      const updated = await api.patch<WorkOrderRecord>(`/api/work-orders/${id}`, {
        is_external_work: false,
        external_executor_name: null,
        external_company: null,
        external_quote_number: null,
        external_oc_number: null,
        external_invoice_number: null,
        external_account_number: null,
        external_oc_amount: null,
        responsible_user_id: null,
        participant_user_ids: [],
      });
      setWo(updated);
      setShowConfirm(null);
      toast("success", "La OT volvió a ser interna. Ahora puedes asignar responsable y participantes.");
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "No se pudo volver a OT interna");
    } finally {
      setActionLoading(false);
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

  async function handleSupervisorReview(action: SupervisorReviewAction) {
    if (action === "RETURN" && !supervisorReviewNotes.trim()) {
      toast("error", "Indica el motivo de la devolución al trabajador.");
      return;
    }
    setActionLoading(true);
    try {
      const updated = await api.post<WorkOrderRecord>(
        `/api/work-orders/${id}/supervisor-validation`,
        { action, notes: supervisorReviewNotes.trim() || null },
      );
      setWo(updated);
      setSupervisorReviewNotes("");
      toast(
        "success",
        action === "CLAIM"
          ? "Revisión tomada. Ahora puedes validar o devolver la OT."
          : action === "APPROVE"
            ? "OT validada por el supervisor. El administrador ya puede aprobarla."
            : "OT devuelta al trabajador para corrección.",
      );
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "No se pudo actualizar la revisión");
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
              {user.role === "ADMIN" && wo.status === "COMPLETED" && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="ml-auto"
                  onClick={() => setShowAdminEdit((current) => !current)}
                >
                  <Pencil className="mr-1 h-3.5 w-3.5" />
                  {showAdminEdit ? "Cerrar edición" : "Editar OT"}
                </Button>
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
          {wo.requires_supervisor_validation && wo.status === "COMPLETED" && (
            <div className="mb-4 rounded-lg border border-violet-200 bg-violet-50 p-3 text-sm text-violet-900">
              <strong>Validación del supervisor:</strong>{" "}
              {wo.supervisor_review_status === "APPROVED"
                ? `Validada por ${wo.supervisor_validator_name || "un supervisor"}. El administrador puede aprobar la OT.`
                : wo.supervisor_review_status === "CLAIMED"
                  ? `Revisión tomada por ${wo.supervisor_validator_name || "otro supervisor"}.`
                  : "Pendiente de revisión por un supervisor del área."}
              {wo.supervisor_review_notes && (
                <p className="mt-1">Observación: {wo.supervisor_review_notes}</p>
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
          {wo.submitted_for_review && user.role === "ADMIN" && !wo.is_hallazgo_report && (
            <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              {wo.is_external_work
                ? `Solicitud de trabajo externo enviada por el supervisor. Al aceptarla, quedarás a cargo de coordinar, verificar y cerrar la OT de ${wo.external_executor_name || "la persona externa"}.`
                : "Esta OT fue enviada por el supervisor. Asigna el responsable y los participantes para poder aceptarla y emitirla."}
              {wo.is_external_work && wo.status === "DRAFT" && (
                <div className="mt-2">
                  <Button type="button" size="sm" variant="outline" onClick={() => setShowConfirm("internal")}>
                    Volver a OT interna
                  </Button>
                </div>
              )}
            </div>
          )}

          {wo.is_hallazgo_report && wo.submitted_for_review && user.role === "ADMIN" && (
            <HallazgoReviewPanel wo={wo} onUpdated={(updated) => { setWo(updated); setNotice({ variant: "success", message: "Hallazgo actualizado correctamente." }); }} />
          )}
          {wo.is_hallazgo_report && wo.hallazgo_status === "RETURNED" && wo.created_by_user_id === user.id && (
            <HallazgoEditPanel wo={wo} onUpdated={(updated) => { setWo(updated); setNotice({ variant: "success", message: "Hallazgo reenviado al administrador." }); }} />
          )}

          {wo.submitted_for_review && user.role === "ADMIN" && !wo.is_external_work && !wo.is_hallazgo_report && (
            <div className="mb-4 rounded-lg border border-cyan-200 bg-cyan-50 p-3 text-sm text-cyan-900">
              <p>Si este trabajo lo realizará un contratista, puedes convertir esta solicitud antes de emitirla.</p>
              <Button type="button" size="sm" variant="outline" className="mt-2" onClick={() => setShowConfirm("external")}>Convertir a trabajo externo</Button>
            </div>
          )}

          {/* Info card */}
          <Card className="mb-4">
            <InfoRowEditContext.Provider value={infoRowEditContext}>
            <CardContent className="p-4">
              <InfoRow label="N° OT" value={wo.ot_number} />
              <InfoRow label="Equipo" value={wo.equipment_name} />
              <InfoRow label="Área" value={wo.area_name} />
              <InfoRow label="Sección" value={wo.section_name} />
              {editableInfoRow(
                "Tipo de mantenimiento",
                "maintenance_type",
                wo.maintenance_type,
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={adminEdit.maintenance_type}
                  onChange={(event) => setAdminEdit((current) => ({ ...current, maintenance_type: event.target.value as WorkOrderRecord["maintenance_type"] }))}
                >
                  {MAINTENANCE_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
                </select>,
              )}
              <InfoRow
                label="Controles LOTO / AST"
                value={(wo.loto_controls || []).map((control) => LOTO_CONTROL_LABELS[control]).join(", ") || "Ninguno seleccionado"}
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
              {wo.status !== "COMPLETED" && <InfoRow label="Tiempo estimado" value={wo.estimated_time} />}
              {editableInfoRow(
                "Tiempo trabajado",
                "worked_time",
                wo.work_time_mode === "RANGE"
                  ? `${(wo.work_start_time || "").slice(0, 5)} a ${(wo.work_end_time || "").slice(0, 5)}`
                  : wo.worked_duration_minutes != null ? `${wo.worked_duration_minutes} minutos` : null,
                <div className="space-y-2">
                  <select className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={adminEdit.work_time_mode} onChange={(event) => setAdminEdit((current) => ({ ...current, work_time_mode: event.target.value as WorkTimeMode, work_start_time: "", work_end_time: "", manual_hours: "", manual_minutes: "" }))}>
                    <option value="RANGE">Desde una hora hasta otra</option>
                    <option value="MANUAL">Duración manual</option>
                  </select>
                  {adminEdit.work_time_mode === "RANGE" ? (
                    <div className="grid gap-2 sm:grid-cols-2">
                      <Input type="time" value={adminEdit.work_start_time} onChange={(event) => setAdminEdit((current) => ({ ...current, work_start_time: event.target.value }))} />
                      <Input type="time" value={adminEdit.work_end_time} onChange={(event) => setAdminEdit((current) => ({ ...current, work_end_time: event.target.value }))} />
                    </div>
                  ) : (
                    <div className="grid gap-2 sm:grid-cols-2">
                      <Input type="number" min="0" step="1" placeholder="Horas" value={adminEdit.manual_hours} onChange={(event) => setAdminEdit((current) => ({ ...current, manual_hours: event.target.value }))} />
                      <Input type="number" min="0" max="59" step="1" placeholder="Minutos" value={adminEdit.manual_minutes} onChange={(event) => setAdminEdit((current) => ({ ...current, manual_minutes: event.target.value }))} />
                    </div>
                  )}
                </div>,
              )}
              <InfoRow
                label={wo.is_external_work ? "Persona externa" : "Responsable"}
                value={wo.is_external_work
                  ? wo.external_executor_name
                  : wo.responsible_user_name || <span className="text-orange-600 font-medium">No asignado</span>}
              />
              {wo.is_external_work && <InfoRow label="Empresa contratista" value={wo.external_company} />}
              {wo.participant_names.length > 0 && (
                <InfoRow label="Participantes" value={wo.participant_names.join(", ")} />
              )}
              <InfoRow label="Solicitado por" value={wo.requested_by} />
              {editableInfoRow("Trabajo", "description", wo.description || wo.title, <textarea className="min-h-[70px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={adminEdit.description} onChange={(event) => setAdminEdit((current) => ({ ...current, description: event.target.value }))} />)}
              {editableInfoRow("Recursos requeridos", "resources_required", wo.resources_required, <textarea className="min-h-[60px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={adminEdit.resources_required} onChange={(event) => setAdminEdit((current) => ({ ...current, resources_required: event.target.value }))} />)}
              {editableInfoRow("Riesgos", "risks", wo.risks, <textarea className="min-h-[60px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={adminEdit.risks} onChange={(event) => setAdminEdit((current) => ({ ...current, risks: event.target.value }))} />)}
              {editableInfoRow("Observaciones", "observations", wo.observations, <textarea className="min-h-[60px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={adminEdit.observations} onChange={(event) => setAdminEdit((current) => ({ ...current, observations: event.target.value }))} />)}
              <InfoRow label="N° vale" value={wo.voucher_number} />
              <InfoRow label="Fecha de vale" value={wo.voucher_date ? formatDateOnly(wo.voucher_date) : null} />
              <InfoRow label="Códigos de materiales" value={wo.material_codes} />
              <InfoRow label="Creado por" value={wo.created_by_name} />
              <InfoRow label="Creado el" value={wo.created_at ? new Date(wo.created_at).toLocaleString("es-CL") : null} />
            </CardContent>
            </InfoRowEditContext.Provider>
          </Card>

          {user.role === "SUPERVISOR" &&
            wo.requires_supervisor_validation &&
            wo.status === "COMPLETED" &&
            (wo.supervisor_review_status === "PENDING" ||
              (wo.supervisor_review_status === "CLAIMED" &&
                wo.supervisor_validator_user_id === user.id)) && (
              <Card className="mb-4 border-violet-200">
                <CardContent className="p-4">
                  <h3 className="text-sm font-semibold text-violet-900">Revisión del supervisor</h3>
                  {wo.supervisor_review_status === "PENDING" && (
                    <>
                      <p className="mt-1 text-sm text-muted-foreground">
                        Esta OT fue creada por un supervisor y requiere validación del área antes de la aprobación administrativa.
                      </p>
                      <Button
                        className="mt-3"
                        disabled={actionLoading}
                        onClick={() => handleSupervisorReview("CLAIM")}
                      >
                        {actionLoading ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Eye className="mr-1 h-4 w-4" />}
                        Tomar revisión
                      </Button>
                    </>
                  )}
                  {wo.supervisor_review_status === "CLAIMED" &&
                    wo.supervisor_validator_user_id === user.id && (
                    <>
                      <p className="mt-1 text-sm text-muted-foreground">
                        Revisa el trabajo y deja una observación si corresponde.
                      </p>
                      <textarea
                        className="mt-3 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        rows={3}
                        value={supervisorReviewNotes}
                        onChange={(event) => setSupervisorReviewNotes(event.target.value)}
                        placeholder="Observación de la revisión (obligatoria si devuelves)"
                      />
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Button disabled={actionLoading} onClick={() => handleSupervisorReview("APPROVE")}>
                          <CheckCircle className="mr-1 h-4 w-4" /> Validar trabajo
                        </Button>
                        <Button variant="outline" disabled={actionLoading} onClick={() => handleSupervisorReview("RETURN")}>
                          <RotateCcw className="mr-1 h-4 w-4" /> Devolver al trabajador
                        </Button>
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>
            )}

          <WorkOrderEvidencePanel
            woId={wo.id}
            stage={wo.status === "IN_PROGRESS" ? "WORK" : "ISSUE"}
            currentUserId={user.id}
            canUpload={
              (wo.is_hallazgo_report && wo.submitted_for_review && wo.created_by_user_id === user.id) ||
              (user.role === "ADMIN" || user.role === "SUPERVISOR") &&
              (wo.status === "DRAFT" || wo.status === "PENDING" || wo.status === "IN_PROGRESS")
            }
            canDeleteAny={
              user.role === "ADMIN" &&
              wo.status !== "APPROVED" &&
              wo.status !== "CANCELLED"
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
                {officialDurationMinutes != null && (
                  <InfoRow label="Duración oficial" value={`${officialDurationMinutes} minutos`} />
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

          {user.role === "ADMIN" && wo.status === "COMPLETED" && showAdminEdit && (
            <Card className="mb-4 border-amber-200 bg-amber-50/40">
              <CardContent className="space-y-4 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="font-semibold text-amber-950">Editar datos de la OT</h3>
                  <p className="mt-1 text-xs text-amber-900/80">
                    Modifica solo los campos necesarios antes de aprobar. Los cambios se reflejarán en la OT de Drive.
                  </p>
                  </div>
                  <button
                    type="button"
                    className="rounded-md p-1 text-amber-900/70 hover:bg-amber-100"
                    aria-label="Cerrar edición"
                    onClick={() => setShowAdminEdit(false)}
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium">Descripción del trabajo</label>
                  <textarea
                    className="min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={adminEdit.description}
                    onChange={(event) => setAdminEdit((current) => ({ ...current, description: event.target.value }))}
                  />
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="text-sm font-medium">Sección
                    <select
                      className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      value={adminEdit.area_id ?? ""}
                      onChange={(event) => {
                        const areaId = event.target.value ? Number(event.target.value) : null;
                        const section = sections.find((item) => item.id === areaId);
                        setAdminEdit((current) => ({
                          ...current,
                          area_id: areaId,
                          section_name: section?.name || "",
                          equipment_id: null,
                        }));
                      }}
                    >
                      <option value="">Sin sección</option>
                      {sections.map((section) => (
                        <option key={section.id} value={section.id}>{section.name}</option>
                      ))}
                    </select>
                    <select
                      className="mt-2 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      value={adminEdit.equipment_id ?? ""}
                      onChange={(event) => setAdminEdit((current) => ({ ...current, equipment_id: event.target.value ? Number(event.target.value) : null }))}
                      disabled={!adminEdit.area_id}
                    >
                      <option value="">Seleccionar equipo de la secciÃ³n</option>
                      {(sections.find((section) => section.id === adminEdit.area_id)?.equipment || []).map((equipment) => (
                        <option key={equipment.id} value={equipment.id}>{equipment.name}</option>
                      ))}
                    </select>
                  </label>
                  <label className="text-sm font-medium">Tipo de mantenimiento
                    <select
                      className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      value={adminEdit.maintenance_type}
                      onChange={(event) => setAdminEdit((current) => ({ ...current, maintenance_type: event.target.value as WorkOrderRecord["maintenance_type"] }))}
                    >
                      {MAINTENANCE_TYPES.map((type) => (
                        <option key={type.value} value={type.value}>{type.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="text-sm font-medium">Fecha ejecución<Input type="date" className="mt-1" value={adminEdit.execution_date} onChange={(event) => setAdminEdit((current) => ({ ...current, execution_date: event.target.value }))} /></label>
                </div>
                <div className="rounded-md border border-input bg-background/60 p-3">
                  <p className="text-sm font-semibold">Tiempo trabajado</p>
                  <p className="mt-1 text-xs text-muted-foreground">Elige una sola forma de registrar las horas: desde / hasta o duración manual.</p>
                  <select
                    className="mt-3 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={adminEdit.work_time_mode}
                    onChange={(event) => setAdminEdit((current) => ({
                      ...current,
                      work_time_mode: event.target.value as WorkTimeMode,
                      work_start_time: "",
                      work_end_time: "",
                      manual_hours: "",
                      manual_minutes: "",
                    }))}
                  >
                    <option value="RANGE">Desde una hora hasta otra</option>
                    <option value="MANUAL">Duración manual</option>
                  </select>
                  {adminEdit.work_time_mode === "RANGE" ? (
                    <div className="mt-3 grid gap-3 sm:grid-cols-2">
                      <label className="text-sm font-medium">Hora de inicio<Input type="time" className="mt-1" value={adminEdit.work_start_time} onChange={(event) => setAdminEdit((current) => ({ ...current, work_start_time: event.target.value }))} /></label>
                      <label className="text-sm font-medium">Hora de término<Input type="time" className="mt-1" value={adminEdit.work_end_time} onChange={(event) => setAdminEdit((current) => ({ ...current, work_end_time: event.target.value }))} /></label>
                    </div>
                  ) : (
                    <div className="mt-3 grid gap-3 sm:grid-cols-2">
                      <label className="text-sm font-medium">Horas<Input type="number" min="0" step="1" className="mt-1" value={adminEdit.manual_hours} onChange={(event) => setAdminEdit((current) => ({ ...current, manual_hours: event.target.value }))} /></label>
                      <label className="text-sm font-medium">Minutos<Input type="number" min="0" max="59" step="1" className="mt-1" value={adminEdit.manual_minutes} onChange={(event) => setAdminEdit((current) => ({ ...current, manual_minutes: event.target.value }))} /></label>
                    </div>
                  )}
                </div>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <label className="text-sm font-medium">Folio<Input className="mt-1" value={adminEdit.folio} onChange={(event) => setAdminEdit((current) => ({ ...current, folio: event.target.value }))} /></label>
                  <label className="text-sm font-medium">N° de vale<Input className="mt-1" value={adminEdit.voucher_number} onChange={(event) => setAdminEdit((current) => ({ ...current, voucher_number: event.target.value }))} /></label>
                  <label className="text-sm font-medium">Fecha de vale<Input type="date" className="mt-1" value={adminEdit.voucher_date} onChange={(event) => setAdminEdit((current) => ({ ...current, voucher_date: event.target.value }))} /></label>
                </div>
                <label className="block text-sm font-medium">Códigos de materiales<Input className="mt-1" value={adminEdit.material_codes} onChange={(event) => setAdminEdit((current) => ({ ...current, material_codes: event.target.value }))} placeholder="Código 1-Código 2-Código 3" /><span className="mt-1 block text-xs font-normal text-muted-foreground">Separa varios códigos con guion (-).</span></label>
                <div className="grid gap-3 sm:grid-cols-3">
                  <label className="text-sm font-medium">Recursos<textarea className="mt-1 min-h-[70px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={adminEdit.resources_required} onChange={(event) => setAdminEdit((current) => ({ ...current, resources_required: event.target.value }))} /></label>
                  <label className="text-sm font-medium">Riesgos<textarea className="mt-1 min-h-[70px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={adminEdit.risks} onChange={(event) => setAdminEdit((current) => ({ ...current, risks: event.target.value }))} /></label>
                  <label className="text-sm font-medium">Observaciones<textarea className="mt-1 min-h-[70px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={adminEdit.observations} onChange={(event) => setAdminEdit((current) => ({ ...current, observations: event.target.value }))} /></label>
                </div>
                <Button type="button" onClick={() => void saveAdminEdit()} disabled={savingAdminEdit}>
                  {savingAdminEdit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Guardar correcciones
                </Button>
              </CardContent>
            </Card>
          )}

          {/* ── Action Buttons ─────────────────────────────────────────── */}
          {!showConfirm && wo.status === "DRAFT" && !wo.is_hallazgo_report && (
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

          {!showConfirm &&
            user.role === "ADMIN" &&
            wo.is_external_work &&
            wo.status === "DRAFT" &&
            !wo.submitted_for_review && (
              <Button variant="outline" className="mt-2 w-full" onClick={() => setShowConfirm("internal")}>
                Volver a OT interna
              </Button>
            )}

          {!showConfirm && wo.status === "COMPLETED" && user.role === "ADMIN" && (
            <div className="flex gap-2">
              <Button variant="outline" className="flex-1" onClick={() => setShowConfirm("return")}>
                <RotateCcw className="mr-1 h-4 w-4" /> Devolver
              </Button>
              {(!wo.requires_supervisor_validation || wo.supervisor_review_status === "APPROVED") ? (
                <Button className="flex-1" onClick={() => setShowConfirm("approve")}>
                  <CheckCircle className="mr-1 h-4 w-4" /> Aprobar
                </Button>
              ) : (
                <div className="flex flex-1 items-center justify-center rounded-md border border-violet-200 bg-violet-50 px-3 text-center text-xs text-violet-800">
                  Esperando validación del supervisor del área
                </div>
              )}
            </div>
          )}

          {!showConfirm &&
            user.role === "ADMIN" &&
            (wo.status === "PENDING" || wo.status === "IN_PROGRESS") && (
            <Button variant="destructive" className="w-full" onClick={() => setShowConfirm("cancel")}>
              <XCircle className="mr-1 h-4 w-4" /> Cancelar OT
            </Button>
            )}

          {/* Reasignar — solo managers, en estados activos (no terminales) */}
          {!showConfirm &&
            user.role === "ADMIN" &&
            !wo.is_external_work &&
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

          {showConfirm === "external" && (
            <ConfirmDialog
              title="Configurar trabajo externo"
              description="La OT no tendrá trabajadores internos. El administrador quedará a cargo de coordinar, verificar y cerrar el trabajo."
              confirmLabel="Guardar externo"
              busy={actionLoading}
              disabled={!externalExecutorName.trim()}
              onConfirm={handleConvertToExternal}
              onCancel={() => { setShowConfirm(null); setExternalExecutorName(""); setExternalCompany(""); }}
            >
              <div className="space-y-3">
                <label className="block text-sm font-medium">Persona externa
                  <input className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={externalExecutorName} onChange={(event) => setExternalExecutorName(event.target.value)} placeholder="Nombre de quien realizará el trabajo" autoFocus />
                </label>
                <label className="block text-sm font-medium">Empresa (opcional)
                  <input className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={externalCompany} onChange={(event) => setExternalCompany(event.target.value)} placeholder="Empresa contratista" />
                </label>
              </div>
            </ConfirmDialog>
          )}

          {showConfirm === "internal" && (
            <ConfirmDialog
              title="¿Volver a OT interna?"
              description="Se eliminarán los datos de la persona externa y la empresa. Después podrás asignar un responsable y participantes internos."
              confirmLabel="Sí, volver a interna"
              busy={actionLoading}
              onConfirm={handleConvertToInternal}
              onCancel={() => setShowConfirm(null)}
            />
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
