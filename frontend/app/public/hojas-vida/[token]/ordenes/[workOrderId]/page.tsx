"use client";

import { use, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { ArrowLeft, ExternalLink, Loader2, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { signatureImageUrl } from "@/lib/signatures";
import type { EquipmentLifeWorkOrderView } from "@/lib/types";

function dateLabel(value: string | null) {
  if (!value) return "—";
  const [year, month, day] = value.slice(0, 10).split("-");
  return day && month && year ? `${day}-${month}-${year}` : value;
}

function dateTimeLabel(value: string | null) {
  return value ? new Date(value).toLocaleString("es-CL") : "—";
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value?.trim()) return null;
  return <div className="rounded-lg border border-slate-200 p-3"><div className="text-xs font-medium text-slate-500">{label}</div><div className="mt-1 whitespace-pre-wrap text-sm text-slate-900">{value}</div></div>;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="mb-5"><h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{children}</div></section>;
}

function EvidenceItem({ token, workOrderId, item }: {
  token: string;
  workOrderId: number;
  item: EquipmentLifeWorkOrderView["evidence"][number];
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  async function showEvidence() {
    if (url) return;
    setError("");
    setLoading(true);
    try {
      const blob = await api.getBlob(`/api/equipment-life/public/${encodeURIComponent(token)}/work-orders/${workOrderId}/evidence/${item.id}/content`);
      setUrl(URL.createObjectURL(blob));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo abrir la evidencia.");
    } finally {
      setLoading(false);
    }
  }

  return <div className="rounded-lg border border-slate-200 p-3">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm font-medium">{item.filename}</p><p className="text-xs text-slate-500">{item.stage === "ISSUE" ? "Foto al emitir" : "Foto del trabajo"} · {item.uploaded_by_name} · {dateTimeLabel(item.uploaded_at)}</p></div><button type="button" onClick={() => void showEvidence()} disabled={loading} className="rounded-md border px-3 py-2 text-sm text-blue-700 disabled:opacity-60">{loading ? "Cargando…" : url ? "Foto cargada" : "Abrir foto"}</button></div>
    {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
    {url && /* eslint-disable-next-line @next/next/no-img-element */ <img src={url} alt={item.filename} className="mt-3 max-h-[520px] w-full rounded-lg bg-slate-50 object-contain" />}
  </div>;
}

function Signature({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  const source = value.startsWith("data:image/") ? value : /^https?:\/\//i.test(value) ? signatureImageUrl(value) : "";
  return <div className="rounded-lg border border-slate-200 p-3"><div className="text-xs font-medium text-slate-500">{label}</div>{source ? /* eslint-disable-next-line @next/next/no-img-element */ <img src={source} alt={label} className="mt-2 max-h-28 max-w-56 object-contain" /> : <p className="mt-1 text-sm">Firma registrada</p>}</div>;
}

export default function PublicEquipmentLifeWorkOrderPage({ params }: { params: Promise<{ token: string; workOrderId: string }> }) {
  const { token, workOrderId } = use(params);
  const [record, setRecord] = useState<EquipmentLifeWorkOrderView | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    api.get<EquipmentLifeWorkOrderView>(`/api/equipment-life/public/${encodeURIComponent(token)}/work-orders/${workOrderId}`)
      .then((result) => { if (active) setRecord(result); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "No se pudo cargar el detalle de la OT."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token, workOrderId]);

  return <main className="min-h-screen bg-slate-50 px-4 py-6 text-slate-900 sm:px-8 sm:py-10"><div className="mx-auto max-w-6xl">
    <header className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-4"><div><div className="font-bold tracking-[0.2em] text-slate-700">MALTEXCO</div><p className="mt-1 text-sm text-slate-500">Consulta pública de orden de trabajo</p></div><span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-800"><ShieldCheck className="h-4 w-4" />Solo lectura</span></header>
    <Link href={`/public/hojas-vida/${encodeURIComponent(token)}`} className="mb-4 inline-flex items-center gap-1 text-sm text-blue-700 hover:underline"><ArrowLeft className="h-4 w-4" />Volver a la hoja de vida</Link>
    {loading && <div className="flex items-center gap-2 rounded-xl border bg-white p-6 text-sm text-slate-600"><Loader2 className="h-4 w-4 animate-spin" />Cargando detalle…</div>}
    {error && <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-800">{error}</div>}
    {record && <article className="mt-3 rounded-2xl border bg-white p-5 shadow-sm sm:p-7">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 pb-4"><div><p className="font-mono text-sm font-semibold text-blue-700">{record.ot_number}</p><h1 className="mt-1 text-2xl font-bold">{record.title}</h1><p className="mt-1 text-sm text-slate-600">{record.equipment_name}</p></div><div className="flex flex-wrap items-center gap-2"><span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs">{record.status}</span><span className="rounded-full bg-blue-50 px-3 py-1.5 text-xs text-blue-800">{record.maintenance_type}</span>{record.google_ot_url && <a href={record.google_ot_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50">Abrir OT en Drive <ExternalLink className="h-4 w-4" /></a>}</div></div>

      <Section title="Datos de la OT">
        <Field label="Fecha de solicitud" value={dateLabel(record.request_date)} /><Field label="Fecha programada" value={dateLabel(record.scheduled_date)} /><Field label="Fecha de ejecución" value={dateLabel(record.execution_date)} /><Field label="Fecha límite" value={dateLabel(record.due_date)} />
        <Field label="Área / planta" value={record.plant_area_name} /><Field label="Sección" value={record.section_name} /><Field label="Área funcional" value={record.area_name} /><Field label="Tipo de mantenimiento" value={record.maintenance_type} />
        <Field label="Solicitada por" value={record.requested_by} /><Field label="Responsable" value={record.responsible_user} /><Field label="Participantes" value={[...record.participants, ...record.participant_names].join(", ")} /><Field label="Realizada por" value={record.performed_by} />
        <Field label="Tiempo estimado" value={record.estimated_time} /><Field label="Tiempo real trabajado" value={record.worked_duration_minutes ? `${record.worked_duration_minutes} min` : record.actual_duration_minutes ? `${record.actual_duration_minutes} min` : null} /><Field label="N.º de vale" value={record.voucher_number} /><Field label="Fecha de vale" value={dateLabel(record.voucher_date)} />
      </Section>

      <Section title="Descripción y ejecución"><Field label="Título" value={record.title} /><Field label="Descripción del trabajo" value={record.description} /><Field label="Observaciones" value={record.observations} /><Field label="Notas de término" value={record.completion_notes} /><Field label="Repuestos / recursos" value={record.resources_required} /><Field label="Códigos de materiales" value={record.material_codes} /><Field label="Riesgos informados" value={record.risks} /><Field label="Controles LOTO" value={record.loto_controls.join(", ") || record.loto_status} /></Section>

      {record.is_external_work && <Section title="Datos del trabajo externo"><Field label="Ejecutor externo" value={record.external_executor_name} /><Field label="Empresa" value={record.external_company} /><Field label="Cotización" value={record.external_quote_number} /><Field label="Orden de compra" value={record.external_oc_number} /><Field label="Factura" value={record.external_invoice_number} /><Field label="Cuenta" value={record.external_account_number} /></Section>}

      <Section title="Trazabilidad y aprobación"><Field label="Creada por" value={record.created_by} /><Field label="Fecha de creación" value={dateTimeLabel(record.created_at)} /><Field label="Última actualización" value={dateTimeLabel(record.updated_at)} /><Field label="Inició el trabajo" value={dateTimeLabel(record.started_at)} /><Field label="Iniciado por" value={record.started_by} /><Field label="Finalización" value={dateTimeLabel(record.completed_at)} /><Field label="Finalizado por" value={record.completed_by} /><Field label="Aprobación" value={dateTimeLabel(record.approved_at)} /><Field label="Aprobado por" value={record.approved_by_user || record.approved_by} /><Field label="Estado de validación" value={record.requires_supervisor_validation ? record.supervisor_review_status : null} /><Field label="Supervisor validador" value={record.supervisor_validator} /><Field label="Fecha de revisión" value={dateTimeLabel(record.supervisor_reviewed_at)} /><Field label="Notas de revisión" value={record.supervisor_review_notes} /><Field label="Devolución" value={dateTimeLabel(record.returned_at)} /><Field label="Motivo de devolución" value={record.return_reason} /><Field label="Motivo de cancelación" value={record.cancellation_reason} /></Section>

      {(record.requested_signature || record.approved_signature) && <section className="mb-5"><h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Firmas</h2><div className="grid gap-3 sm:grid-cols-2"><Signature label="Firma solicitante" value={record.requested_signature} /><Signature label="Firma de aprobación" value={record.approved_signature} /></div></section>}

      <section><h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Evidencias fotográficas ({record.evidence.length})</h2>{record.evidence.length ? <div className="grid gap-3">{record.evidence.map((item) => <EvidenceItem key={item.id} token={token} workOrderId={record.work_order_id} item={item} />)}</div> : <p className="rounded-lg border border-dashed p-4 text-sm text-slate-600">Esta OT no tiene fotos adjuntas.</p>}</section>
    </article>}
    <footer className="mt-6 text-center text-xs text-slate-500">Enlace público de consulta. No permite modificar la OT ni muestra herramientas para crear códigos QR.</footer>
  </div></main>;
}
