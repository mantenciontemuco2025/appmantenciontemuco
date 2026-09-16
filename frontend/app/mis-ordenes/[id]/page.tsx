"use client";

import { useEffect, useState, use, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Loader2, Play, CheckCircle, Clock, AlertTriangle, Save } from "lucide-react";
import { api, cacheOfflineResponse, isOfflineQueued } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/layout/shell";
import type { WorkOrderRecord, LotoControl, WorkTimeMode } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { InlineAlert } from "@/components/ui/inline-alert";
import { VoiceDictation } from "@/components/maintenance/voice-dictation";
import { StatusBadge, MAINTENANCE_TYPES, maintenanceTypeLabel } from "@/lib/status";
import { signatureImageUrl } from "@/lib/signatures";
import { SyncBadge } from "@/components/maintenance/sync-badge";
import { PageLoading } from "@/components/ui/page-loading";
import { formatDurationLong, formatDateOnly, todayDateInputValue } from "@/lib/utils";
import { LOTO_CONTROL_OPTIONS } from "@/lib/loto";
import { WorkOrderEvidencePanel } from "@/components/maintenance/work-order-evidence";

const inputCls =
  "w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";
const labelCls = "block text-sm font-medium mb-1.5";
const hintCls = "text-xs text-muted-foreground mb-2";

interface FulfillForm {
  maintenance_type: string;
  loto_controls: LotoControl[];
  execution_date: string;   // fecha de ejecución — la coloca el trabajador
  time_mode: WorkTimeMode;
  start_time: string;
  end_time: string;
  estimated_time: string;   // legacy planning value
  manual_hours: string;
  manual_minutes: string;
  resources_required: string;
  risks: string;
  observations: string;
  folio: string;
  voucher_number: string;
}

interface AlertState {
  variant: "success" | "error";
  message: string;
}

type AutoSaveState = "idle" | "saving" | "saved" | "queued" | "error";

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  if (!value) return null;
  return (
    <div className="py-2 border-b border-border last:border-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-sm font-medium">{value}</div>
    </div>
  );
}

export default function MisOrdenDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [wo, setWo] = useState<WorkOrderRecord | null>(null);
  const [loadingOrder, setLoadingOrder] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [showConfirm, setShowConfirm] = useState<"start" | "complete" | null>(null);
  const [completionNotes, setCompletionNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<AlertState | null>(null);
  const [form, setForm] = useState<FulfillForm>({
    maintenance_type: "PREVENTIVE",
    loto_controls: ["NOT_APPLICABLE"],
    execution_date: "",
    time_mode: "RANGE",
    start_time: "",
    end_time: "",
    estimated_time: "",
    manual_hours: "",
    manual_minutes: "",
    resources_required: "",
    risks: "",
    observations: "",
    folio: "",
    voucher_number: "",
  });
  const [savingFulfill, setSavingFulfill] = useState(false);
  const [autoSaveState, setAutoSaveState] = useState<AutoSaveState>("idle");
  const [autoSaveError, setAutoSaveError] = useState<string | null>(null);
  const [formHydratedId, setFormHydratedId] = useState<string | null>(null);
  const skipAutoSaveRef = useRef(true);
  const latestSaveRef = useRef(0);

  const localDraftKey = user ? `mantencion:fulfill-draft:${user.id}:${id}` : null;

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    setFormHydratedId(null);
    skipAutoSaveRef.current = true;
    loadOrder(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, id]);

  async function loadOrder(hydrateForm = false) {
    if (hydrateForm) {
      setLoadingOrder(true);
      setError(null);
    }
    try {
      const data = await api.get<WorkOrderRecord>(`/api/work-orders/${id}`);
      setWo(data);
      if (hydrateForm) {
        let localDraft: Partial<FulfillForm> = {};
        if (localDraftKey) {
          try {
            const raw = window.localStorage.getItem(localDraftKey);
            if (raw) {
              const parsed = JSON.parse(raw) as { form?: Partial<FulfillForm> };
              localDraft = parsed.form || {};
            }
          } catch {
            localDraft = {};
          }
        }
        // Prefill once. Polling later updates only the OT status and never
        // overwrites text the worker may currently be typing.
        setForm((f) => ({
          ...f,
          maintenance_type: data.maintenance_type || "PREVENTIVE",
          loto_controls:
            data.loto_controls?.length
              ? data.loto_controls
              : data.loto_status === "YES"
                ? ["LOTO_BLOQUEO"]
                : ["NOT_APPLICABLE"],
          execution_date:
            (data.execution_date || "").slice(0, 10) ||
            todayDateInputValue(),
          time_mode: data.work_time_mode || "RANGE",
          start_time: (data.work_start_time || "").slice(0, 5),
          end_time: (data.work_end_time || "").slice(0, 5),
          manual_hours:
            data.worked_duration_minutes != null
              ? String(Math.floor(data.worked_duration_minutes / 60))
              : "",
          manual_minutes:
            data.worked_duration_minutes != null
              ? String(data.worked_duration_minutes % 60)
              : "",
          estimated_time: data.estimated_time || "",
          resources_required: data.resources_required || "",
          risks: data.risks || "",
          observations: data.observations || "",
          folio: data.folio || "",
          voucher_number: data.voucher_number || "",
          ...localDraft,
        }));
        setFormHydratedId(id);
      }
    } catch {
      if (hydrateForm) setError("No se pudo cargar la orden de trabajo");
    } finally {
      if (hydrateForm) setLoadingOrder(false);
    }
  }

  useEffect(() => {
    const handleOfflineSynced = () => void loadOrder(false);
    window.addEventListener("mantencion:offline-synced", handleOfflineSynced);
    return () => window.removeEventListener("mantencion:offline-synced", handleOfflineSynced);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // The local workflow returns immediately; keep the integration badges fresh
  // while Drive/Sheets finishes in the background.
  useEffect(() => {
    if (!wo) return;
    const pending = wo.ot_sheet_sync_status === "PENDING" || wo.monthly_sheet_sync_status === "PENDING";
    if (!pending) return;
    const timer = setInterval(() => void loadOrder(false), 2500);
    // Google can take several seconds to create/update both documents. Keep
    // the status fresh long enough without blocking the worker workflow.
    const stop = setTimeout(() => clearInterval(timer), 120000);
    return () => {
      clearInterval(timer);
      clearTimeout(stop);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wo?.ot_sheet_sync_status, wo?.monthly_sheet_sync_status]);

  const isResponsible = user && wo && wo.responsible_user_id === user.id;
  // Can fulfill details while PENDING (before work starts) or IN_PROGRESS
  const canFulfill =
    isResponsible && (wo?.status === "PENDING" || wo?.status === "IN_PROGRESS");

  function toast(variant: AlertState["variant"], message: string) {
    setNotice({ variant, message });
  }

  // Duration from start/end times → estimated_time string
  function deriveEstimatedTime(min: number | null): string {
    if (min == null || min <= 0) return "";
    return formatDurationLong(min);
  }

  function reportedWorkMinutes(values: FulfillForm): number | null {
    if (values.time_mode === "RANGE") {
      if (!values.start_time || !values.end_time) return null;
      const [sh, sm] = values.start_time.split(":").map(Number);
      const [eh, em] = values.end_time.split(":").map(Number);
      const start = sh * 60 + sm;
      const end = eh * 60 + em;
      return end > start ? end - start : null;
    }
    const hours = Number(values.manual_hours);
    const minutes = Number(values.manual_minutes || 0);
    if (!Number.isInteger(hours) || hours < 0) return null;
    if (!Number.isInteger(minutes) || minutes < 0 || minutes > 59) return null;
    const total = hours * 60 + minutes;
    return total > 0 ? total : null;
  }

  function workTimeError(values: FulfillForm): string | null {
    if (values.time_mode === "RANGE") {
      if (!values.start_time || !values.end_time) {
        return "Indica la hora de inicio y la hora de término.";
      }
      if (reportedWorkMinutes(values) == null) {
        return "La hora de término debe ser posterior a la hora de inicio.";
      }
      return null;
    }
    if (reportedWorkMinutes(values) == null) {
      return "Indica una duración manual mayor que cero.";
    }
    return null;
  }

  function updateFormField<K extends keyof FulfillForm>(key: K, value: FulfillForm[K]) {
    const next = { ...form, [key]: value } as FulfillForm;
    setForm(next);
  }

  function toggleLotoControl(control: Exclude<LotoControl, "NOT_APPLICABLE">) {
    const selected = form.loto_controls.includes(control)
      ? form.loto_controls.filter((item) => item !== control && item !== "NOT_APPLICABLE")
      : [...form.loto_controls.filter((item) => item !== "NOT_APPLICABLE"), control];
    updateFormField("loto_controls", selected.length ? selected : ["NOT_APPLICABLE"]);
  }

  function buildFulfillPayload(values: FulfillForm) {
    return {
      maintenance_type: values.maintenance_type,
      loto_status: values.loto_controls.includes("NOT_APPLICABLE") ? "NOT_APPLICABLE" : "YES",
      loto_controls: values.loto_controls,
      execution_date: values.execution_date || null,
      work_time_mode: values.time_mode,
      work_start_time: values.time_mode === "RANGE" ? values.start_time || null : null,
      work_end_time: values.time_mode === "RANGE" ? values.end_time || null : null,
      worked_duration_minutes:
        values.time_mode === "MANUAL" ? reportedWorkMinutes(values) : null,
      // Keep the planning field unchanged. Completed OTs use the declared
      // duration stored by the completion endpoint for the monthly register.
      estimated_time: values.estimated_time || null,
      resources_required: values.resources_required || null,
      risks: values.risks || null,
      observations: values.observations || null,
      folio: values.folio || null,
      voucher_number: values.voucher_number || null,
    };
  }

  async function autoSaveFulfill(values: FulfillForm) {
    const saveId = ++latestSaveRef.current;
    setAutoSaveState("saving");
    setAutoSaveError(null);
    try {
      const updated = await api.patch<WorkOrderRecord>(
        `/api/work-orders/${id}/fulfill-autosave`,
        buildFulfillPayload(values),
      );
      if (saveId !== latestSaveRef.current) return;
      if (isOfflineQueued(updated)) {
        setAutoSaveState("queued");
        setAutoSaveError("Guardado en el dispositivo; pendiente de sincronización.");
        return;
      }
      setWo(updated);
      setAutoSaveState("saved");
      if (localDraftKey) window.localStorage.removeItem(localDraftKey);
    } catch (err) {
      if (saveId !== latestSaveRef.current) return;
      setAutoSaveState("error");
      setAutoSaveError(err instanceof Error ? err.message : "No se pudo guardar automáticamente");
      // The local backup remains available for the next attempt or a reload.
    }
  }

  useEffect(() => {
    if (formHydratedId !== id || !canFulfill) return;

    // Keep an immediate browser backup so a network interruption cannot erase
    // what the worker has typed while the debounced request is in flight.
    if (localDraftKey) {
      try {
        window.localStorage.setItem(
          localDraftKey,
          JSON.stringify({ form, savedAt: new Date().toISOString() }),
        );
      } catch {
        // Browser storage is a safety net; the online form must still work.
      }
    }

    if (skipAutoSaveRef.current) {
      skipAutoSaveRef.current = false;
      return;
    }

    const timer = window.setTimeout(() => {
      void autoSaveFulfill(form);
    }, 900);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form, formHydratedId, canFulfill, id, localDraftKey]);

  async function handleStart() {
    setActionLoading(true);
    setError(null);
    try {
      const updated = await api.post<WorkOrderRecord>(`/api/work-orders/${id}/start`);
      if (isOfflineQueued(updated)) {
        if (wo && user) {
          const optimistic = {
            ...wo,
            status: "IN_PROGRESS" as const,
            started_at: new Date().toISOString(),
            started_by_user_id: user.id,
            started_by_name: user.full_name,
          };
          setWo(optimistic);
          cacheOfflineResponse(`/api/work-orders/${id}`, optimistic);
        }
        setShowConfirm(null);
        toast("success", "Inicio guardado sin conexión. Se sincronizará al volver Internet.");
        return;
      }
      setWo(updated);
      setShowConfirm(null);
      toast("success", "Trabajo iniciado. Buena jornada!");
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "Error al iniciar la OT");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleComplete() {
    setActionLoading(true);
    try {
      const durationError = workTimeError(form);
      if (durationError) {
        toast("error", durationError);
        setShowConfirm(null);
        return;
      }
      const reportedMinutes = reportedWorkMinutes(form);
      const updated = await api.patch<WorkOrderRecord>(`/api/work-orders/${id}/complete`, {
        completion_notes: completionNotes || null,
        work_time_mode: form.time_mode,
        work_start_time: form.time_mode === "RANGE" ? form.start_time : null,
        work_end_time: form.time_mode === "RANGE" ? form.end_time : null,
        worked_duration_minutes: form.time_mode === "MANUAL" ? reportedMinutes : null,
      });
      if (isOfflineQueued(updated)) {
        if (wo && user) {
          const optimistic = {
            ...wo,
            status: "COMPLETED" as const,
            completed_at: new Date().toISOString(),
            completed_by_user_id: user.id,
            completed_by_name: user.full_name,
            completion_notes: completionNotes || null,
            work_time_mode: form.time_mode,
            worked_duration_minutes: reportedMinutes,
            actual_duration_minutes: reportedMinutes,
          };
          setWo(optimistic);
          cacheOfflineResponse(`/api/work-orders/${id}`, optimistic);
        }
        setShowConfirm(null);
        setCompletionNotes("");
        toast("success", "Finalización guardada sin conexión. Se sincronizará al volver Internet.");
        return;
      }
      setWo(updated);
      setShowConfirm(null);
      setCompletionNotes("");
      toast("success", "OT finalizada y firmada como realizada. Pendiente de revisión del administrador.");
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "Error al finalizar la OT");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleSaveFulfill() {
    ++latestSaveRef.current;
    setSavingFulfill(true);
    setError(null);
    try {
      const updated = await api.patch<WorkOrderRecord>(
        `/api/work-orders/${id}/fulfill`,
        buildFulfillPayload(form),
      );
      if (isOfflineQueued(updated)) {
        setAutoSaveState("queued");
        setAutoSaveError("Guardado en el dispositivo; pendiente de sincronización.");
        toast("success", "Detalles guardados sin conexión. Se sincronizarán al volver Internet.");
        return;
      }
      setWo(updated);
      setAutoSaveState("saved");
      setAutoSaveError(null);
      if (localDraftKey) window.localStorage.removeItem(localDraftKey);
      toast("success", "Detalles de la OT guardados.");
    } catch (err) {
      setAutoSaveState("error");
      setAutoSaveError(err instanceof Error ? err.message : "No se pudo guardar automáticamente");
      toast("error", err instanceof Error ? err.message : "Error al guardar los detalles");
    } finally {
      setSavingFulfill(false);
    }
  }

  if (loading || !user) {
    return <PageLoading message={loading ? "Validando sesión..." : "Redirigiendo al inicio de sesión..."} />;
  }

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      {/* Back button */}
      <Link href="/mis-ordenes" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-4">
        <ArrowLeft className="h-4 w-4" /> Mis Órdenes
      </Link>

      {loadingOrder ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
        </div>
      ) : error && !wo ? (
        <Card>
          <CardContent className="p-6 text-center text-sm text-destructive">
            {error}
          </CardContent>
        </Card>
      ) : wo ? (
        <>
          {/* Header */}
          <div className="mb-4">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-mono text-lg font-bold text-primary">{wo.ot_number}</span>
              <StatusBadge status={wo.status} />
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

          {(wo.ot_sheet_sync_status === "PENDING" || wo.monthly_sheet_sync_status === "PENDING" ||
            wo.ot_sheet_sync_status === "FAILED" || wo.monthly_sheet_sync_status === "FAILED") && (
            <div className="mb-4 rounded-lg border bg-muted/30 p-3 text-sm">
              <p className="mb-2 font-medium">La OT ya quedó guardada. Google se actualiza en segundo plano; puedes continuar sin esperar:</p>
              <div className="flex flex-wrap gap-2">
                <SyncBadge status={wo.ot_sheet_sync_status} />
                <SyncBadge status={wo.monthly_sheet_sync_status} />
              </div>
              {(wo.ot_sheet_sync_error || wo.monthly_sheet_sync_error) && (
                <p className="mt-2 text-xs text-red-600">
                  El trabajo local no se perdió; un administrador puede reintentar la sincronización.
                </p>
              )}
            </div>
          )}

          {/* Status-specific banner */}
          {wo.status === "PENDING" && isResponsible && (
            <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
              <Clock className="inline h-4 w-4 mr-1" />
              Completa los detalles de la OT y luego inicia el trabajo.
            </div>
          )}
          {wo.status === "COMPLETED" && (
            <div className="mb-4 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-800">
              <CheckCircle className="inline h-4 w-4 mr-1" />
              OT finalizada. Pendiente de revisión del administrador.
            </div>
          )}
          {wo.status === "APPROVED" && (
            <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
              <CheckCircle className="inline h-4 w-4 mr-1" />
              OT aprobada y cerrada.
            </div>
          )}
          {wo.status === "CANCELLED" && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              <AlertTriangle className="inline h-4 w-4 mr-1" />
              OT cancelada.
              {wo.cancellation_reason && <> Motivo: {wo.cancellation_reason}</>}
            </div>
          )}

          {/* ── Fulfill form (responsible fills remaining details) ────── */}
          {canFulfill && (
            <Card className="mb-4 border-blue-200">
              <CardContent className="p-4 space-y-4">
                <h3 className="font-semibold text-blue-800 flex items-center gap-2">
                  <Save className="h-4 w-4" /> Completar OT
                </h3>
                <div className="flex items-center justify-between gap-3 rounded-md bg-blue-50 px-3 py-2 text-xs text-blue-800">
                  <span>Los cambios se guardan automáticamente.</span>
                  <span aria-live="polite" className="font-medium">
                    {autoSaveState === "saving" && "Guardando..."}
                    {autoSaveState === "saved" && "Guardado"}
                    {autoSaveState === "queued" && "Pendiente de sincronización"}
                    {autoSaveState === "error" && "Pendiente de reintento"}
                    {autoSaveState === "idle" && "Listo"}
                  </span>
                </div>
                {(autoSaveState === "error" || autoSaveState === "queued") && autoSaveError && (
                  <p className="text-xs text-destructive">
                    No se perdió lo escrito. Se conserva una copia local. {autoSaveError}
                  </p>
                )}

                <Select
                  label="Tipo de mantención"
                  options={MAINTENANCE_TYPES.map((mt) => ({ value: mt.value, label: mt.label }))}
                  value={form.maintenance_type}
                  onChange={(e) => updateFormField("maintenance_type", e.target.value)}
                />

                <div>
                  <label className={labelCls}>LOTO / Bloqueo / AST</label>
                  <div className="grid grid-cols-1 gap-2 rounded-md border border-input p-3 sm:grid-cols-2">
                    {LOTO_CONTROL_OPTIONS.map((option) => (
                      <label key={option.value} className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={form.loto_controls.includes(option.value)}
                          onChange={() => toggleLotoControl(option.value)}
                          className="h-4 w-4 rounded border-input"
                        />
                        {option.label}
                      </label>
                    ))}
                    <label className="flex items-center gap-2 text-sm sm:col-span-2">
                      <input
                        type="checkbox"
                        checked={form.loto_controls.includes("NOT_APPLICABLE")}
                        onChange={() => updateFormField("loto_controls", ["NOT_APPLICABLE"])}
                        className="h-4 w-4 rounded border-input"
                      />
                      No aplica
                    </label>
                  </div>
                  <p className={hintCls}>Puedes seleccionar varias opciones. &quot;No aplica&quot; es exclusiva.</p>
                </div>

                <div>
                  <label className={labelCls}>Fecha de ejecución</label>
                  <Input
                    type="date"
                    value={form.execution_date}
                    onChange={(e) => updateFormField("execution_date", e.target.value)}
                  />
                </div>

                <div>
                  <label className={labelCls}>Cómo registrar las horas trabajadas</label>
                  <Select
                    options={[
                      { value: "RANGE", label: "Desde una hora hasta otra" },
                      { value: "MANUAL", label: "Duración manual" },
                    ]}
                    value={form.time_mode}
                    onChange={(e) => updateFormField("time_mode", e.target.value as WorkTimeMode)}
                  />
                  <p className={hintCls}>Elige solo una forma para registrar las horas.</p>
                </div>

                {form.time_mode === "RANGE" && <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={labelCls}>Hora inicio</label>
                    <Input
                      type="time"
                      value={form.start_time}
                      onChange={(e) => updateFormField("start_time", e.target.value)}
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Hora término</label>
                    <Input
                      type="time"
                      value={form.end_time}
                      onChange={(e) => updateFormField("end_time", e.target.value)}
                    />
                  </div>
                </div>}

                <div>
                  <label className={labelCls}>Duracion manual</label>
                  <p className={hintCls}>
                    Usa estos campos solo si elegiste &quot;Duracion manual&quot;.
                  </p>
                  <div className="grid grid-cols-2 gap-3">
                    <Input
                      type="number"
                      min={0}
                      max={999}
                      step={1}
                      inputMode="numeric"
                      placeholder="Horas"
                      value={form.manual_hours}
                      disabled={form.time_mode !== "MANUAL"}
                      onChange={(e) => updateFormField("manual_hours", e.target.value)}
                    />
                    <Input
                      type="number"
                      min={0}
                      max={59}
                      step={1}
                      inputMode="numeric"
                      placeholder="Minutos"
                      value={form.manual_minutes}
                      disabled={form.time_mode !== "MANUAL"}
                      onChange={(e) => updateFormField("manual_minutes", e.target.value)}
                    />
                  </div>
                  {form.time_mode === "MANUAL" && reportedWorkMinutes(form) != null && (
                    <p className="mt-2 text-sm font-medium text-blue-800">
                      Se registrarÃ¡n {deriveEstimatedTime(reportedWorkMinutes(form))}.
                    </p>
                  )}
                </div>

                <div>
                  <label className={labelCls}>Recursos y materiales</label>
                  <textarea
                    className={`${inputCls} min-h-[60px]`}
                    placeholder="Ej: Grasa EP2, sello SKF, llave 24mm..."
                    value={form.resources_required}
                    onChange={(e) => updateFormField("resources_required", e.target.value)}
                  />
                  <VoiceDictation
                    onTranscript={(text) =>
                      updateFormField(
                        "resources_required",
                        form.resources_required
                          ? `${form.resources_required} ${text}`
                          : text
                      )
                    }
                  />
                </div>

                <div>
                  <label className={labelCls}>Riesgos e identificación de peligros</label>
                  <textarea
                    className={`${inputCls} min-h-[60px]`}
                    placeholder="Ej: Desenergizar equipo, uso de EPP..."
                    value={form.risks}
                    onChange={(e) => updateFormField("risks", e.target.value)}
                  />
                  <VoiceDictation
                    onTranscript={(text) =>
                      updateFormField(
                        "risks",
                        form.risks ? `${form.risks} ${text}` : text
                      )
                    }
                  />
                </div>

                <div>
                  <label className={labelCls}>Observaciones</label>
                  <textarea
                    className={`${inputCls} min-h-[60px]`}
                    value={form.observations}
                    onChange={(e) => updateFormField("observations", e.target.value)}
                  />
                  <VoiceDictation
                    onTranscript={(text) =>
                      updateFormField(
                        "observations",
                        form.observations ? `${form.observations} ${text}` : text
                      )
                    }
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={labelCls}>Folio / permiso</label>
                    <Input
                      value={form.folio}
                      onChange={(e) => updateFormField("folio", e.target.value)}
                    />
                  </div>
                  <div>
                    <label className={labelCls}>N° de vale</label>
                    <Input
                      value={form.voucher_number}
                      onChange={(e) => updateFormField("voucher_number", e.target.value)}
                    />
                  </div>
                </div>

                <Button
                  variant="outline"
                  className="w-full"
                  onClick={handleSaveFulfill}
                  disabled={savingFulfill}
                >
                  {savingFulfill ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Save className="mr-2 h-4 w-4" />
                  )}
                  Guardar ahora
                </Button>
              </CardContent>
            </Card>
          )}

          {/* Info card */}
          <Card className="mb-4">
            <CardContent className="p-4">
              <InfoRow label="N° OT" value={wo.ot_number} />
              <InfoRow label="Equipo" value={wo.equipment_name} />
              <InfoRow label="Área" value={wo.area_name} />
              <InfoRow label="Sección" value={wo.section_name} />
              <InfoRow label="Tipo de mantenimiento" value={maintenanceTypeLabel(wo.maintenance_type)} />
              <InfoRow label="LOTO" value={wo.loto_status === "YES" ? "Sí" : wo.loto_status === "NO" ? "No" : "N/A"} />
              <InfoRow
                label="Fecha de ejecución"
                value={formatDateOnly(wo.execution_date)}
              />
              <InfoRow label="Tiempo estimado" value={wo.estimated_time ? `${wo.estimated_time}` : null} />
              <InfoRow
                label="Fecha de solicitud"
                value={formatDateOnly(wo.request_date)}
              />
              <InfoRow
                label="Responsable"
                value={wo.responsible_user_name || <span className="text-muted-foreground">No asignado</span>}
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
            </CardContent>
          </Card>

          <WorkOrderEvidencePanel
            woId={wo.id}
            stage="WORK"
            currentUserId={user.id}
            canUpload={
              user.role === "WORKER" &&
              wo.responsible_user_id === user.id &&
              (wo.status === "PENDING" || wo.status === "IN_PROGRESS")
            }
          />

          {/* Lifecycle info */}
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
                  <InfoRow label="DuraciÃ³n manual" value={formatDurationLong(wo.worked_duration_minutes)} />
                )}
                {wo.actual_duration_minutes != null && (
                  <InfoRow label="Horas declaradas por trabajador" value={formatDurationLong(wo.actual_duration_minutes)} />
                )}
                {wo.completion_notes && <InfoRow label="Notas de finalización" value={wo.completion_notes} />}
              </CardContent>
            </Card>
          )}

          {/* Action buttons */}
          {wo.status === "PENDING" && isResponsible && !showConfirm && (
            <Button className="w-full" onClick={() => setShowConfirm("start")}>
              <Play className="mr-2 h-4 w-4" /> Iniciar Trabajo
            </Button>
          )}

          {wo.status === "IN_PROGRESS" && isResponsible && !showConfirm && (
            <Button
              className="w-full"
              onClick={() => {
                const durationError = workTimeError(form);
                if (durationError) {
                  toast("error", durationError);
                  return;
                }
                setShowConfirm("complete");
              }}
            >
              <CheckCircle className="mr-2 h-4 w-4" /> Finalizar Trabajo
            </Button>
          )}

          {/* Confirmation dialogs */}
          {showConfirm === "start" && (
            <ConfirmDialog
              title="¿Iniciar trabajo?"
              description={
                <>
                  Se registrará la hora de inicio. La OT cambiará a <strong>En proceso</strong>.
                </>
              }
              confirmLabel="Sí, iniciar"
              busy={actionLoading}
              onConfirm={handleStart}
              onCancel={() => setShowConfirm(null)}
            />
          )}

          {showConfirm === "complete" && (
            <ConfirmDialog
              title="¿Finalizar trabajo?"
              description={
                <>
                  La OT cambiará a <strong>Finalizado</strong> para revisión del admin.
                </>
              }
              confirmLabel="Sí, finalizar"
              tone="success"
              busy={actionLoading}
              disabled={!user.signature}
              onConfirm={handleComplete}
              onCancel={() => { setShowConfirm(null); setCompletionNotes(""); }}
            >
              {user.signature ? (
                <div className="mb-3 rounded-md border bg-white p-2">
                  <p className="mb-2 text-xs text-muted-foreground">
                    Se aplicará tu nombre y firma manuscrita en <strong>REALIZADO POR</strong>.
                  </p>
                  <img src={signatureImageUrl(user.signature)} alt="Tu firma" className="h-14 w-full object-contain" />
                </div>
              ) : (
                <InlineAlert variant="warning" className="mb-3">
                  Debes cargar tu firma en <Link href="/perfil" className="font-medium underline">Mi firma</Link> antes de finalizar.
                </InlineAlert>
              )}
              <div className="mb-3">
                <label className="text-sm font-medium">Notas de finalización (opcional)</label>
                <textarea
                  className={`${inputCls} mt-1 min-h-[72px]`}
                  rows={3}
                  placeholder="Describe el trabajo realizado..."
                  value={completionNotes}
                  onChange={(e) => setCompletionNotes(e.target.value)}
                />
              </div>
            </ConfirmDialog>
          )}

          {/* Return reason if returned */}
          {wo.return_reason && (
            <Card className="mb-4 border-orange-200">
              <CardContent className="p-4">
                <h3 className="text-sm font-semibold text-orange-800 mb-1">Devoluido por el admin</h3>
                <p className="text-sm text-orange-700">{wo.return_reason}</p>
              </CardContent>
            </Card>
          )}
        </>
      ) : null}
    </Shell>
  );
}
