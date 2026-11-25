"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { ExternalLink, FileText, Loader2, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { PublicEquipmentLifeDetail } from "@/lib/types";

function dateLabel(value: string | null) {
  if (!value) return "—";
  const [year, month, day] = value.slice(0, 10).split("-");
  return day && month && year ? `${day}-${month}-${year}` : value;
}

export default function PublicEquipmentLifePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const [detail, setDetail] = useState<PublicEquipmentLifeDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    api.get<PublicEquipmentLifeDetail>(`/api/equipment-life/public/${encodeURIComponent(token)}`)
      .then((result) => { if (active) setDetail(result); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "No se pudo cargar la hoja de vida."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token]);

  return <main className="min-h-screen bg-slate-50 px-4 py-6 text-slate-900 sm:px-8 sm:py-10">
    <div className="mx-auto max-w-6xl">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-4">
        <div><div className="font-bold tracking-[0.2em] text-slate-700">MALTEXCO</div><p className="mt-1 text-sm text-slate-500">Consulta de hoja de vida de equipo</p></div>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-800"><ShieldCheck className="h-4 w-4" />Solo lectura</span>
      </header>

      {loading && <div className="flex items-center gap-2 rounded-xl border bg-white p-6 text-sm text-slate-600"><Loader2 className="h-4 w-4 animate-spin" />Cargando hoja de vida…</div>}
      {error && <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-800">{error}</div>}
      {detail && <>
        <section className="mb-5 rounded-2xl border bg-white p-5 shadow-sm sm:p-7">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div><h1 className="text-2xl font-bold sm:text-3xl">{detail.equipment_name}</h1><p className="mt-2 text-slate-600">{detail.plant_area_name || "Área sin especificar"}{detail.section_name ? ` · ${detail.section_name}` : ""}</p></div>
            {detail.life_sheet_url && <a className="inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50" href={detail.life_sheet_url} target="_blank" rel="noreferrer"><ExternalLink className="h-4 w-4" />Abrir hoja en Drive</a>}
          </div>
          <div className="mt-5 rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-600">Historial de trabajos: <strong className="text-slate-900">{detail.records.length}</strong> OT</div>
        </section>

        <section className="rounded-2xl border bg-white p-5 shadow-sm sm:p-7">
          <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold"><FileText className="h-5 w-5 text-blue-600" />Historial de mantención</h2>
          {detail.records.length ? <div className="space-y-3">{detail.records.map((record) => <article key={record.work_order_id} className="rounded-xl border p-4 sm:p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-sm font-semibold text-blue-700">{record.ot_number}</span><span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-700">{record.status}</span><span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs text-blue-800">{record.maintenance_type}</span></div><h3 className="mt-2 font-semibold">{record.title}</h3></div>
              <div className="text-sm text-slate-600">{dateLabel(record.event_date)}</div>
            </div>
            {record.description && <p className="mt-3 whitespace-pre-wrap text-sm text-slate-700">{record.description}</p>}
            <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div><span className="text-xs text-slate-500">Realizado por</span><p>{record.performed_by || "—"}</p></div>
              <div><span className="text-xs text-slate-500">Duración real</span><p>{record.worked_duration || "—"}</p></div>
              <div className="sm:col-span-2"><span className="text-xs text-slate-500">Repuestos</span><p className="whitespace-pre-wrap">{record.resources_required || "—"}</p></div>
            </div>
            {record.observations && <p className="mt-3 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm text-slate-700"><span className="font-medium">Observaciones: </span>{record.observations}</p>}
            <div className="mt-4 flex flex-wrap gap-3 border-t pt-3 text-sm">
              <Link className="font-medium text-blue-700 hover:underline" href={`/public/hojas-vida/${encodeURIComponent(token)}/ordenes/${record.work_order_id}`}>Ver detalle de la OT</Link>
              {record.google_ot_url && <a className="inline-flex items-center gap-1 text-blue-700 hover:underline" href={record.google_ot_url} target="_blank" rel="noreferrer">Abrir OT en Drive <ExternalLink className="h-3.5 w-3.5" /></a>}
            </div>
          </article>)}</div> : <p className="rounded-lg border border-dashed p-5 text-sm text-slate-600">Este equipo aún no tiene OT visibles en su hoja de vida.</p>}
        </section>
      </>}
      <footer className="mt-6 text-center text-xs text-slate-500">Enlace público de consulta. No permite modificar la información.</footer>
    </div>
  </main>;
}
