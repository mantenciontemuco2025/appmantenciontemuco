"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ExternalLink, FileSpreadsheet, Loader2, RefreshCw, Search } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { PageLoading } from "@/components/ui/page-loading";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { EquipmentLifeBackfillAccepted, EquipmentLifeBackfillStatus, EquipmentLifeDetail, EquipmentLifeSummary } from "@/lib/types";

function statusLabel(status: string) {
  if (status === "SYNCED") return "Sincronizada";
  if (status === "FAILED") return "Con error";
  return "Pendiente";
}

function dateLabel(value: string | null) {
  if (!value) return "—";
  const [year, month, day] = value.slice(0, 10).split("-");
  return day && month && year ? `${day}-${month}-${year}` : value;
}

export default function EquipmentLifePage() {
  const { user, loading, logout } = useAuth();
  const [items, setItems] = useState<EquipmentLifeSummary[]>([]);
  const [selected, setSelected] = useState<EquipmentLifeDetail | null>(null);
  const [search, setSearch] = useState("");
  const [sectionFilter, setSectionFilter] = useState("");
  const [onlyWithRecords, setOnlyWithRecords] = useState(false);
  const [loadingData, setLoadingData] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillStatus, setBackfillStatus] = useState<EquipmentLifeBackfillStatus | null>(null);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  async function loadItems() {
    setLoadingData(true);
    setMessage(null);
    try {
      setItems(await api.get<EquipmentLifeSummary[]>("/api/equipment-life"));
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "No se pudo cargar el historial." });
    } finally {
      setLoadingData(false);
    }
  }

  useEffect(() => {
    if (user) void loadItems();
  }, [user]);

  async function openDetail(item: EquipmentLifeSummary) {
    setLoadingDetail(true);
    setMessage(null);
    try {
      setSelected(await api.get<EquipmentLifeDetail>(`/api/equipment-life/${item.equipment_id}`));
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "No se pudo cargar la hoja de vida." });
    } finally {
      setLoadingDetail(false);
    }
  }

  async function getBackfillStatusWithRetry() {
    let lastError: unknown;
    for (let retry = 0; retry < 3; retry += 1) {
      try {
        return await api.get<EquipmentLifeBackfillStatus>("/api/equipment-life/status");
      } catch (error) {
        lastError = error;
        if (retry < 2) await new Promise((resolve) => window.setTimeout(resolve, 2000));
      }
    }
    throw lastError instanceof Error ? lastError : new Error("No se pudo consultar el avance de la importación.");
  }

  async function backfill() {
    if (!window.confirm("Se actualizarán las hojas de vida de todas las OT que tengan equipo asignado. ¿Continuar?")) return;
    setBackfilling(true);
    setBackfillStatus(null);
    setMessage(null);
    try {
      const accepted = await api.post<EquipmentLifeBackfillAccepted & { sheets_synced: number; work_orders_synced: number; work_orders_without_equipment: number }>("/api/equipment-life/backfill", { include_drafts: false }, 30000);
      const result = accepted;
      setMessage({ kind: "success", text: accepted.message });
      let statusFailures = 0;
      for (let attempt = 0; attempt < 180; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 5000));
        let state: EquipmentLifeBackfillStatus;
        try {
          state = await getBackfillStatusWithRetry();
          statusFailures = 0;
        } catch (error) {
          statusFailures += 1;
          if (statusFailures >= 3) throw error;
          setMessage({ kind: "success", text: "No se pudo consultar temporalmente el avance. La importación puede seguir ejecutándose; reintentando..." });
          continue;
        }
        setBackfillStatus(state);
        await loadItems();
        if (state.status === "running") {
          const total = state.work_orders_total;
          const synced = state.work_orders_synced;
          const remaining = Math.max(total - synced, 0);
          const percent = total > 0 ? Math.min(100, Math.round((synced / total) * 100)) : 0;
          const current = state.current_equipment ? ` Equipo actual: ${state.current_equipment}.` : "";
          setMessage({ kind: "success", text: `Sincronizando ${percent}% - ${synced}/${total} OT. Faltan ${remaining} OT; equipos ${state.equipment_processed}/${state.equipment_total}.${current}` });
        }
        if (state.status === "completed") {
          const completed = state.result;
          setMessage({ kind: "success", text: completed ? `ImportaciÃ³n terminada: ${completed.sheets_synced} hojas y ${completed.work_orders_synced} OT sincronizadas. ${completed.work_orders_without_equipment} OT quedaron sin equipo.` : "ImportaciÃ³n terminada correctamente." });
          if (selected) await openDetail(selected);
          return;
        }
        if (state.status === "failed") {
          throw new Error(state.error || "La importaciÃ³n fallÃ³. Revisa el estado del backend.");
        }
        if (attempt === 179) throw new Error("La importaciÃ³n sigue en curso. Revisa nuevamente en unos minutos.");
      }
      return;
      if (false) {
      setMessage({ kind: "success", text: `Importación terminada: ${result.sheets_synced} hojas y ${result.work_orders_synced} OT sincronizadas. ${result.work_orders_without_equipment} OT quedaron sin equipo.` });
      await loadItems();
      const currentSelected = selected;
      if (currentSelected) await openDetail(currentSelected as EquipmentLifeSummary);
      }
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "No se pudo ejecutar la importación." });
    } finally {
      setBackfilling(false);
    }
  }

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((item) => [item.equipment_name, item.section_name, item.plant_area_name].some((value) => value?.toLowerCase().includes(needle)));
  }, [items, search]);

  const sections = useMemo(() => Array.from(new Set(items.filter((item) => item.work_order_count > 0 && item.section_name).map((item) => item.section_name as string))).sort((a, b) => a.localeCompare(b, "es")), [items]);
  const visibleItems = useMemo(() => filtered.filter((item) => (!onlyWithRecords || item.work_order_count > 0) && (!sectionFilter || item.section_name === sectionFilter)), [filtered, onlyWithRecords, sectionFilter]);

  if (loading || !user) return <PageLoading message={loading ? "Validando sesión..." : "Redirigiendo..."} />;

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div><h1 className="text-2xl font-bold">Hojas de vida de equipos</h1><p className="mt-1 text-sm text-muted-foreground">Historial de trabajos por equipo, guardado en la base de datos y en Google Drive.</p></div>
        <div className="flex gap-2"><Button variant="outline" onClick={() => void loadItems()} disabled={loadingData}><RefreshCw className="mr-2 h-4 w-4" />Actualizar</Button>{user.role === "ADMIN" && <Button onClick={() => void backfill()} disabled={backfilling}>{backfilling ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileSpreadsheet className="mr-2 h-4 w-4" />}{backfilling ? "Importando..." : "Importar todas las OT"}</Button>}</div>
      </div>

      {message && <div className={`mb-4 rounded-lg border p-3 text-sm ${message.kind === "error" ? "border-red-200 bg-red-50 text-red-800" : "border-green-200 bg-green-50 text-green-800"}`}>{message.text}</div>}

      {backfilling && backfillStatus?.status === "running" && (() => {
        const percent = backfillStatus.work_orders_total > 0 ? Math.min(100, Math.round((backfillStatus.work_orders_synced / backfillStatus.work_orders_total) * 100)) : 0;
        return <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950">
          <div className="mb-2 flex items-center justify-between font-semibold"><span>Sincronización en curso</span><span>{percent}%</span></div>
          <div className="h-2 overflow-hidden rounded-full bg-blue-100"><div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${percent}%` }} /></div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs"><span>OT: {backfillStatus.work_orders_synced}/{backfillStatus.work_orders_total}</span><span>Faltan: {Math.max(backfillStatus.work_orders_total - backfillStatus.work_orders_synced, 0)}</span><span>Equipos: {backfillStatus.equipment_processed}/{backfillStatus.equipment_total}</span>{backfillStatus.current_equipment && <span>Actual: {backfillStatus.current_equipment}</span>}</div>
        </div>;
      })()}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <section className="rounded-xl border bg-card p-4">
          <div className="mb-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_180px]"><div className="relative"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><input className="h-10 w-full rounded-md border bg-background pl-9 pr-3 text-sm" placeholder="Buscar equipo o sección..." value={search} onChange={(event) => setSearch(event.target.value)} /></div><select className="h-10 rounded-md border bg-background px-3 text-sm" value={sectionFilter} onChange={(event) => setSectionFilter(event.target.value)}><option value="">Secciones con registros</option>{sections.map((section) => <option key={section} value={section}>{section}</option>)}</select></div>
          <label className="mb-3 flex items-center gap-2 text-sm text-muted-foreground"><input type="checkbox" checked={onlyWithRecords} onChange={(event) => setOnlyWithRecords(event.target.checked)} className="h-4 w-4 rounded border-input" />Solo equipos con registros ({items.filter((item) => item.work_order_count > 0).length})</label>
          {loadingData ? <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Cargando equipos...</div> : <div className="max-h-[650px] space-y-2 overflow-auto">{visibleItems.map((item) => <button key={item.equipment_id} type="button" onClick={() => void openDetail(item)} className={`w-full rounded-lg border p-3 text-left transition-colors hover:border-primary ${selected?.equipment_id === item.equipment_id ? "border-primary bg-primary/5" : ""}`}><div className="font-semibold">{item.equipment_name}</div><div className="mt-1 text-xs text-muted-foreground">{item.section_name || "Sin sección"}{item.plant_area_name ? ` · ${item.plant_area_name}` : ""}</div><div className="mt-2 flex items-center justify-between text-xs"><span>{item.work_order_count} OT registradas</span><span className={item.life_sheet_sync_status === "SYNCED" ? "text-green-700" : item.life_sheet_sync_status === "FAILED" ? "text-red-700" : "text-amber-700"}>{statusLabel(item.life_sheet_sync_status)}</span></div></button>)}{!visibleItems.length && <p className="py-8 text-sm text-muted-foreground">No hay equipos que coincidan con los filtros.</p>}</div>}
        </section>

        <section className="rounded-xl border bg-card p-4">
          {!selected ? <div className="flex min-h-[240px] items-center justify-center text-center text-sm text-muted-foreground">Selecciona un equipo para ver sus registros.</div> : <><div className="flex flex-wrap items-start justify-between gap-3 border-b pb-3"><div><h2 className="text-xl font-semibold">{selected.equipment_name}</h2><p className="text-sm text-muted-foreground">{selected.section_name || "Sin sección"}{selected.plant_area_name ? ` · ${selected.plant_area_name}` : ""}</p></div>{selected.life_sheet_url && <a className="inline-flex items-center gap-1 text-sm text-primary hover:underline" href={selected.life_sheet_url} target="_blank" rel="noreferrer">Abrir en Drive <ExternalLink className="h-3.5 w-3.5" /></a>}</div><div className="mt-4 overflow-x-auto"><table className="w-full min-w-[680px] text-left text-sm"><thead><tr className="border-b text-xs uppercase text-muted-foreground"><th className="px-2 py-2">Fecha</th><th className="px-2 py-2">OT</th><th className="px-2 py-2">Trabajo</th><th className="px-2 py-2">Realizado por</th><th className="px-2 py-2">Estado</th><th className="px-2 py-2">Tipo</th></tr></thead><tbody>{selected.records.map((record) => <tr key={record.work_order_id} className="border-b last:border-0"><td className="px-2 py-2 whitespace-nowrap">{dateLabel(record.event_date)}</td><td className="px-2 py-2 whitespace-nowrap font-medium"><Link className="text-primary hover:underline" href={`${user.role === "WORKER" ? "/mis-ordenes" : "/ordenes"}/${record.work_order_id}`}>{record.ot_number}</Link></td><td className="max-w-[240px] px-2 py-2">{record.description || record.title}</td><td className="px-2 py-2">{record.performed_by || "—"}</td><td className="px-2 py-2">{record.status}</td><td className="px-2 py-2">{record.maintenance_type}</td></tr>)}</tbody></table>{!selected.records.length && <p className="py-8 text-sm text-muted-foreground">Este equipo aún no tiene OT registradas.</p>}</div></>}
          {loadingDetail && <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Cargando detalle...</div>}
        </section>
      </div>
    </Shell>
  );
}
