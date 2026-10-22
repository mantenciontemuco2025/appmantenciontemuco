"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Camera, Loader2, LockKeyhole, X } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { PageLoading } from "@/components/ui/page-loading";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { LOTO_CONTROL_LABELS } from "@/lib/loto";
import type { EquipmentLifeWorkOrderView } from "@/lib/types";

function dateLabel(value: string | null) {
  if (!value) return "—";
  const [year, month, day] = value.slice(0, 10).split("-");
  return day && month && year ? `${day}-${month}-${year}` : value;
}

function durationLabel(minutes: number | null) {
  if (minutes == null || minutes <= 0) return "—";
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return [hours ? `${hours} h` : "", remainder ? `${remainder} min` : ""]
    .filter(Boolean)
    .join(" ") || "0 min";
}

function dateTimeLabel(value: string | null) {
  return value ? new Date(value).toLocaleString("es-CL") : "—";
}

function timeLabel(value: string | null) {
  return value ? value.slice(0, 5) : null;
}

function DetailField({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value?.trim()) return null;
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="mt-1 whitespace-pre-wrap text-sm">{value}</div>
    </div>
  );
}

function EvidencePhoto({ equipmentId, workOrderId, evidence }: {
  equipmentId: number;
  workOrderId: number;
  evidence: EquipmentLifeWorkOrderView["evidence"][number];
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [loadingPhoto, setLoadingPhoto] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  async function openPhoto() {
    setError("");
    if (url) return;
    setLoadingPhoto(true);
    try {
      const blob = await api.getBlob(`/api/equipment-life/equipment/${equipmentId}/work-orders/${workOrderId}/evidence/${evidence.id}/content`);
      setUrl(URL.createObjectURL(blob));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo cargar la foto.");
    } finally {
      setLoadingPhoto(false);
    }
  }

  function closePhoto() {
    if (url) URL.revokeObjectURL(url);
    setUrl(null);
  }

  return <>
    <div className="flex items-center justify-between gap-3 rounded-lg border p-3">
      <div className="min-w-0"><div className="truncate text-sm font-medium" title={evidence.filename}>{evidence.filename}</div><div className="mt-1 text-xs text-muted-foreground">{evidence.stage === "ISSUE" ? "Foto al emitir" : "Foto del trabajo realizado"} · {evidence.uploaded_by_name} · {dateTimeLabel(evidence.uploaded_at)}</div>{error && <div className="mt-1 text-xs text-red-700">{error}</div>}</div>
      <Button type="button" size="sm" variant="outline" disabled={loadingPhoto} onClick={() => void openPhoto()}>{loadingPhoto ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Camera className="mr-2 h-4 w-4" />}{loadingPhoto ? "Cargando…" : "Abrir foto"}</Button>
    </div>
    {url && <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/85 p-3 sm:p-6" role="dialog" aria-modal="true" aria-label={`Visualizador de ${evidence.filename}`} onClick={closePhoto}><div className="relative flex max-h-full w-full max-w-6xl flex-col" onClick={(event) => event.stopPropagation()}><div className="mb-3 flex items-center justify-between gap-3 text-white"><div className="min-w-0"><p className="truncate font-semibold">{evidence.filename}</p><p className="text-xs text-white/75">{evidence.stage === "ISSUE" ? "Foto al emitir" : "Foto del trabajo realizado"} · {evidence.uploaded_by_name}</p></div><button type="button" className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/15 text-white hover:bg-white/25" onClick={closePhoto} aria-label="Cerrar foto"><X className="h-6 w-6" /></button></div><div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden rounded-xl bg-black/40">{/* eslint-disable-next-line @next/next/no-img-element */}<img src={url} alt={evidence.filename} className="max-h-[78vh] max-w-full object-contain" /></div></div></div>}
  </>;
}

function SignatureField({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  const source = value.startsWith("data:image/") || /^https?:\/\//i.test(value) ? value : null;
  return <div className="rounded-lg border p-3"><div className="text-xs font-medium text-muted-foreground">{label}</div>{source ? <img src={source} alt={label} className="mt-2 max-h-24 max-w-48 object-contain" /> : <div className="mt-1 text-sm">Firma registrada</div>}</div>;
}

export default function EquipmentLifeWorkOrderPage({
  params,
}: {
  params: Promise<{ equipmentId: string; workOrderId: string }>;
}) {
  const { equipmentId, workOrderId } = use(params);
  const { user, loading, logout } = useAuth();
  const [record, setRecord] = useState<EquipmentLifeWorkOrderView | null>(null);
  const [loadingRecord, setLoadingRecord] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user) return;
    let active = true;
    setLoadingRecord(true);
    setError("");
    api.get<EquipmentLifeWorkOrderView>(
      `/api/equipment-life/equipment/${equipmentId}/work-orders/${workOrderId}`,
    )
      .then((data) => {
        if (active) setRecord(data);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "No se pudo cargar la OT.");
      })
      .finally(() => {
        if (active) setLoadingRecord(false);
      });
    return () => {
      active = false;
    };
  }, [user, equipmentId, workOrderId]);

  if (loading || !user) {
    return <PageLoading message={loading ? "Validando sesión..." : "Redirigiendo..."} />;
  }

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href="/hojas-vida" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
            <ArrowLeft className="h-4 w-4" /> Volver a hojas de vida
          </Link>
          <h1 className="mt-2 text-2xl font-bold">Detalle de orden de trabajo</h1>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border bg-muted px-3 py-1.5 text-xs font-medium text-muted-foreground">
          <LockKeyhole className="h-3.5 w-3.5" /> Solo lectura
        </span>
      </div>

      {loadingRecord && (
        <div className="flex items-center gap-2 rounded-lg border p-5 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Cargando orden...
        </div>
      )}
      {!loadingRecord && error && (
        <div className="space-y-3">
          <InlineAlert variant="error">{error}</InlineAlert>
          <Link href="/hojas-vida"><Button variant="outline">Volver a hojas de vida</Button></Link>
        </div>
      )}
      {!loadingRecord && record && (
        <article className="rounded-xl border bg-card p-5 shadow-sm">
          <header className="mb-5 flex flex-wrap items-start justify-between gap-3 border-b pb-4">
            <div>
              <p className="font-mono text-sm font-semibold text-primary">{record.ot_number}</p>
              {record.original_ot_number && (
                <p className="mt-1 text-xs text-muted-foreground">OT original: {record.original_ot_number}</p>
              )}
              <h2 className="mt-2 text-xl font-semibold">{record.title}</h2>
            </div>
            <div className="flex gap-2">
              <span className="rounded-full bg-blue-50 px-3 py-1 text-sm text-blue-800">{record.status}</span>
              <span className="rounded-full bg-muted px-3 py-1 text-sm">{record.maintenance_type}</span>
            </div>
          </header>

          <section className="mb-5"><h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Datos de la OT</h3><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <DetailField label="Fecha de solicitud" value={dateLabel(record.request_date)} />
            <DetailField label="Fecha programada" value={dateLabel(record.scheduled_date)} />
            <DetailField label="Fecha de ejecución" value={dateLabel(record.execution_date || record.event_date)} />
            <DetailField label="Fecha límite" value={dateLabel(record.due_date)} />
            <DetailField label="Área / planta" value={record.plant_area_name} />
            <DetailField label="Sección" value={record.section_name} />
            <DetailField label="Equipo" value={record.equipment_name} />
            <DetailField label="Área funcional" value={record.area_name} />
            <DetailField label="Tipo de mantenimiento" value={record.maintenance_type} />
            <DetailField label="Estado" value={record.status} />
            <DetailField label="Planificación" value={record.is_planned ? "Planificada" : "No planificada"} />
            <DetailField label="Estado de envío a revisión" value={record.submitted_for_review ? "Enviada a revisión" : null} />
            <DetailField label="Solicitada por" value={record.requested_by} />
            <DetailField label="Responsable" value={record.responsible_user} />
            <DetailField label="Participantes" value={record.participants.join(", ") || (record.participant_names || []).join(", ") || null} />
            <DetailField label="Realizada por" value={record.performed_by} />
            <DetailField label="Folio" value={record.folio} />
            <DetailField label="N.º de vale" value={record.voucher_number} />
            <DetailField label="Fecha de vale" value={dateLabel(record.voucher_date)} />
            <DetailField label="Códigos de materiales utilizados" value={record.material_codes} />
            <DetailField label="Tiempo estimado" value={record.estimated_time} />
            <DetailField label="Controles LOTO" value={(record.loto_controls || []).map((control) => LOTO_CONTROL_LABELS[control as keyof typeof LOTO_CONTROL_LABELS] || control).join(", ") || record.loto_status} />
            <DetailField label="Tiempo estimado" value={record.work_time_mode === "RANGE" ? `${timeLabel(record.work_start_time) || "—"} a ${timeLabel(record.work_end_time) || "—"}` : durationLabel(record.worked_duration_minutes)} />
            <DetailField label="Tiempo real trabajado" value={record.actual_duration_minutes != null ? durationLabel(Math.round(record.actual_duration_minutes)) : durationLabel(record.worked_duration_minutes)} />
          </div></section>

          <section className="mb-5"><h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Descripción y ejecución</h3><div className="grid gap-3">
            <DetailField label="Título" value={record.title} />
            <DetailField label="Descripción del trabajo" value={record.description} />
            <DetailField label="Trabajo realizado / notas de cierre" value={record.completion_notes} />
            <DetailField label="Observaciones" value={record.observations} />
            <DetailField label="Recursos requeridos o utilizados" value={record.resources_required} />
            <DetailField label="Riesgos informados" value={record.risks} />
          </div></section>

          {record.is_external_work && <section className="mb-5"><h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Datos del trabajo externo</h3><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <DetailField label="Ejecutor externo" value={record.external_executor_name} />
            <DetailField label="Empresa" value={record.external_company} />
            <DetailField label="Cotización" value={record.external_quote_number} />
            <DetailField label="Orden de compra" value={record.external_oc_number} />
            <DetailField label="Factura" value={record.external_invoice_number} />
            <DetailField label="Cuenta" value={record.external_account_number} />
          </div></section>}

          <section className="mb-5"><h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Trazabilidad y aprobación</h3><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <DetailField label="Creada por" value={record.created_by} />
            <DetailField label="Fecha de creación" value={dateTimeLabel(record.created_at)} />
            <DetailField label="Última actualización" value={dateTimeLabel(record.updated_at)} />
            <DetailField label="Inicio del trabajo" value={dateTimeLabel(record.started_at)} />
            <DetailField label="Iniciado por" value={record.started_by} />
            <DetailField label="Finalización" value={dateTimeLabel(record.completed_at)} />
            <DetailField label="Finalizado por" value={record.completed_by} />
            <DetailField label="Aprobación" value={dateTimeLabel(record.approved_at)} />
            <DetailField label="Aprobado por" value={record.approved_by_user || record.approved_by} />
            <DetailField label="Validación de supervisor" value={record.requires_supervisor_validation ? record.supervisor_review_status : null} />
            <DetailField label="Supervisor validador" value={record.supervisor_validator} />
            <DetailField label="Fecha de revisión" value={dateTimeLabel(record.supervisor_reviewed_at)} />
            <DetailField label="Devolución" value={dateTimeLabel(record.returned_at)} />
            <DetailField label="Motivo de devolución" value={record.return_reason} />
            <DetailField label="Motivo de cancelación" value={record.cancellation_reason} />
          </div><div className="mt-3 grid gap-3"><DetailField label="Observación de revisión del supervisor" value={record.supervisor_review_notes} /></div></section>

          {(record.is_historical || record.hallazgo_folio) && <section className="mb-5"><h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Antecedentes históricos / hallazgo</h3><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <DetailField label="Tipo de OT" value={record.is_historical ? "Histórica" : "Hallazgo convertido"} />
            <DetailField label="Folio de hallazgo" value={record.hallazgo_folio} />
            <DetailField label="Clasificación" value={record.hallazgo_kind} />
            <DetailField label="Prioridad" value={record.hallazgo_priority} />
            <DetailField label="Estado del hallazgo" value={record.hallazgo_status} />
            <DetailField label="Revisado por" value={record.hallazgo_reviewed_by_name} />
            <DetailField label="Fecha de revisión del hallazgo" value={dateTimeLabel(record.hallazgo_reviewed_at)} />
            <DetailField label="Notas de revisión del hallazgo" value={record.hallazgo_review_notes} />
          </div></section>}

          {(record.requested_signature || record.approved_signature) && <section className="mb-5"><h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Firmas</h3><div className="grid gap-3 sm:grid-cols-2"><SignatureField label="Firma solicitante" value={record.requested_signature} /><SignatureField label="Firma de aprobación" value={record.approved_signature} /></div></section>}

          <section><h3 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground"><Camera className="h-4 w-4" />Evidencias fotográficas ({record.evidence?.length ?? 0})</h3>{record.evidence?.length ? <div className="grid gap-2">{record.evidence.map((item) => <EvidencePhoto key={item.id} equipmentId={record.equipment_id} workOrderId={record.work_order_id} evidence={item} />)}</div> : <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">Esta OT no tiene fotos adjuntas.</p>}</section>
        </article>
      )}
    </Shell>
  );
}
