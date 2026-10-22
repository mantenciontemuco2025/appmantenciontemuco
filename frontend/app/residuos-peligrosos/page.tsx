"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { AlertCircle, Biohazard, Check, ExternalLink, Loader2, Plus, RefreshCw, Save } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PageLoading } from "@/components/ui/page-loading";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type RecordRow = {
  id: number; entry_date: string; respel_code: string | null; waste_name: string;
  hazard: string | null; origin: string | null; quantity: string | null; unit: string;
  accumulated_quantity: string | null; delivered_by: string | null; disposal_date: string | null;
  manager: string | null; source_sheet: string | null; sheet_row: number | null;
  sync_status: string; sync_error: string | null; sheet_synced_at: string | null;
};
type Form = {
  entry_date: string; respel_code: string; waste_name: string; hazard: string;
  origin: string; quantity: string; delivered_by: string;
  disposal_date: string; manager: string;
};
const emptyForm = (): Form => ({ entry_date: new Date().toISOString().slice(0, 10), respel_code: "", waste_name: "", hazard: "", origin: "", quantity: "", delivered_by: "", disposal_date: "", manager: "" });
const defaultSheet = "https://docs.google.com/spreadsheets/d/1XksaPDWi--vnvervuwG0w0wEAH5kogUT4_NA8VAkSXY/edit?usp=sharing";
const dateText = (value: string | null) => value ? new Date(`${value}T12:00:00`).toLocaleDateString("es-CL") : "—";
const amount = (value: string | number | null, unit = "") => value === null ? "—" : `${Number(value).toLocaleString("es-CL", { maximumFractionDigits: 3 })}${unit ? ` ${unit}` : ""}`;
function uniqueOptions(values: Array<string | null | undefined>) {
  const options = new Map<string, string>();
  values.forEach((value) => {
    const trimmed = value?.trim();
    if (trimmed && !options.has(trimmed.toLocaleLowerCase("es"))) {
      options.set(trimmed.toLocaleLowerCase("es"), trimmed);
    }
  });
  return Array.from(options.values()).sort((a, b) => a.localeCompare(b, "es", { sensitivity: "base" }));
}

export default function HazardousWastePage() {
  const { user, loading, logout } = useAuth();
  const [configured, setConfigured] = useState(false);
  const [environmentConfigured, setEnvironmentConfigured] = useState(false);
  const [configurationError, setConfigurationError] = useState("");
  const [sheetUrl, setSheetUrl] = useState(defaultSheet);
  const [spreadsheetUrl, setSpreadsheetUrl] = useState("");
  const [records, setRecords] = useState<RecordRow[]>([]);
  const [form, setForm] = useState<Form>(emptyForm());
  const [editing, setEditing] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [storedOnly, setStoredOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [disposing, setDisposing] = useState<RecordRow | null>(null);
  const [disposalDate, setDisposalDate] = useState("");
  const [disposalManager, setDisposalManager] = useState("LOGISAMB");
  const [bulkDisposalOpen, setBulkDisposalOpen] = useState(false);
  const [serverStoredCount, setServerStoredCount] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const status = await api.get<{ configured: boolean; environment_configured?: boolean; configuration_error?: string | null; spreadsheet_url?: string | null; stored_records?: number }>("/api/hazardous-waste/status");
      setConfigured(status.configured);
      setServerStoredCount(typeof status.stored_records === "number" ? status.stored_records : null);
      setEnvironmentConfigured(Boolean(status.environment_configured));
      setConfigurationError(status.configuration_error || "");
      if (status.spreadsheet_url) setSheetUrl(status.spreadsheet_url);
      setSpreadsheetUrl(status.spreadsheet_url || "");
      if (status.configured) {
        // Keep the full local history available for autocomplete, then filter it
        // in the UI so suggestions don't disappear when the history search changes.
        setRecords(await api.get<RecordRow[]>("/api/hazardous-waste"));
      } else {
        setRecords([]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar el registro.");
    }
  }, []);

  useEffect(() => { if (user?.role === "ADMIN") void load(); }, [user, load]);
  useEffect(() => {
    if (!records.some((row) => row.sync_status === "PENDING" || row.sync_status === "SYNCING")) return;
    const timer = window.setInterval(() => { void load(); }, 4000);
    return () => window.clearInterval(timer);
  }, [records, load]);
  const storedCount = useMemo(() => serverStoredCount ?? records.filter((r) => !r.disposal_date).length, [records, serverStoredCount]);
  const visibleRecords = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase("es");
    return records.filter((row) => {
      if (storedOnly && row.disposal_date) return false;
      if (!needle) return true;
      return [row.waste_name, row.respel_code, row.origin]
        .some((value) => value?.toLocaleLowerCase("es").includes(needle));
    });
  }, [records, search, storedOnly]);
  const options = useMemo(() => ({
    codes: uniqueOptions(records.map((row) => row.respel_code)),
    wasteNames: uniqueOptions(records.map((row) => row.waste_name)),
    hazards: uniqueOptions(records.map((row) => row.hazard)),
    origins: uniqueOptions(records.map((row) => row.origin)),
    people: uniqueOptions(records.flatMap((row) => [row.delivered_by, row.manager])),
  }), [records]);

  async function connectSheet(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const result = await api.post<{ imported: number; message: string }>("/api/hazardous-waste/setup", { spreadsheet_url: sheetUrl }, 120000);
      setConfigured(true); setMessage(`${result.message} Se importaron ${result.imported} ingresos.`); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "No se pudo conectar la planilla."); }
    finally { setBusy(false); }
  }

  async function saveRecord(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    const body = { ...form, unit: "", respel_code: form.respel_code || null, hazard: form.hazard || null, origin: form.origin || null, delivered_by: form.delivered_by || null, disposal_date: form.disposal_date || null, manager: form.manager || null, quantity: form.quantity.trim() ? Number(form.quantity) : null };
    try {
      await (editing ? api.put(`/api/hazardous-waste/${editing}`, body) : api.post("/api/hazardous-waste", body));
      setMessage(editing ? "Ingreso actualizado; se recalculó el acumulado." : "Ingreso guardado; se calculará el acumulado automáticamente.");
      setForm(emptyForm()); setEditing(null); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "No se pudo guardar el ingreso."); }
    finally { setBusy(false); }
  }

  function editRecord(row: RecordRow) {
    setEditing(row.id); setForm({ entry_date: row.entry_date, respel_code: row.respel_code || "", waste_name: row.waste_name, hazard: row.hazard || "", origin: row.origin || "", quantity: row.quantity || "", delivered_by: row.delivered_by || "", disposal_date: row.disposal_date || "", manager: row.manager || "" });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function retry(id: number) {
    try { await api.post(`/api/hazardous-waste/${id}/retry`); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "No se pudo reintentar la sincronización."); }
  }

  function beginDisposal(row: RecordRow) {
    const today = new Date();
    const localDate = new Date(today.getTime() - today.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    setDisposing(row); setDisposalDate(localDate); setDisposalManager("LOGISAMB"); setError(""); setMessage("");
  }

  async function registerDisposal(event: FormEvent) {
    event.preventDefault();
    if (!disposing) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api.post<{ updated: number }>(`/api/hazardous-waste/${disposing.id}/dispose`, {
        disposal_date: disposalDate, manager: disposalManager.trim(),
      });
      setMessage(`Retiro registrado: ${result.updated} ingresos de ${disposing.waste_name} actualizados. El acumulado comenzará de cero después de la fecha de retiro.`);
      setDisposing(null);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "No se pudo registrar el retiro."); }
    finally { setBusy(false); }
  }

  function beginBulkDisposal() {
    const now = new Date();
    const localDate = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    setDisposalDate(localDate);
    setDisposalManager("LOGISAMB");
    setBulkDisposalOpen(true);
    setDisposing(null);
    setError("");
    setMessage("");
  }

  async function registerBulkDisposal(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api.post<{ updated: number; disposal_date: string; manager: string }>("/api/hazardous-waste/dispose-all", {
        disposal_date: disposalDate, manager: disposalManager.trim(),
      });
      setMessage(`Retiro masivo registrado: ${result.updated} ingresos quedaron como retirados por ${result.manager} el ${dateText(result.disposal_date)}. El stock se recalculó y se sincronizará con Google Sheets.`);
      setBulkDisposalOpen(false);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "No se pudo registrar el retiro masivo."); }
    finally { setBusy(false); }
  }

  if (loading || !user) return <PageLoading message={loading ? "Validando sesión…" : "Redirigiendo al inicio de sesión…"} />;
  if (user.role !== "ADMIN") return <Shell fullName={user.full_name} role={user.role} onLogout={logout}><Card className="p-6">Este módulo está disponible solo para administradores.</Card></Shell>;

  return <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div className="flex items-center gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-xl bg-amber-100 text-amber-800"><Biohazard className="h-6 w-6" /></span><div><h1 className="text-2xl font-bold">Residuos peligrosos</h1><p className="text-muted-foreground">Ingresos, almacenamiento y disposición; acumulados calculados por residuo.</p></div></div>
      {configured && <a className="inline-flex items-center gap-2 text-sm text-primary hover:underline" href={spreadsheetUrl} target="_blank" rel="noreferrer">Abrir planilla <ExternalLink className="h-4 w-4" /></a>}
    </div>
    {(error || message) && <div className={`mb-4 rounded-lg border p-3 text-sm ${error ? "border-red-200 bg-red-50 text-red-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error || message}</div>}

    {configurationError ? <Card className="mb-6 border-red-200 bg-red-50 p-5 text-red-800"><h2 className="font-semibold">Configuración de planilla no coincide</h2><p className="mt-1 text-sm">{configurationError} Revisa GOOGLE_HAZARDOUS_WASTE_SPREADSHEET_ID en Render; no borres registros de la base.</p></Card> : !configured ? <Card className="mb-6 p-5 sm:p-6"><h2 className="text-lg font-semibold">Conectar planilla de Google</h2><p className="mb-4 mt-1 text-sm text-muted-foreground">Usaremos la planilla que compartiste como copia de trabajo. El historial anual se guardará en la base de la app y se mantendrá sincronizado en este archivo. La pestaña de stock no se importará para evitar duplicados.</p><form onSubmit={connectSheet} className="space-y-3"><label className="block text-sm font-medium">{environmentConfigured ? "Planilla fijada para este entorno" : "Enlace de Google Sheets"}<Input className="mt-1" type="url" value={sheetUrl} onChange={(e) => setSheetUrl(e.target.value)} readOnly={environmentConfigured} required /></label><p className="text-xs text-muted-foreground">{environmentConfigured ? "El ID se obtiene de la variable de entorno de este backend." : "La cuenta de Google configurada en el backend necesita permiso de edición sobre este archivo."}</p><Button disabled={busy}>{busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}{busy ? "Conectando e importando…" : "Conectar e importar historial"}</Button></form></Card> : <>
      <Card className="mb-6 p-4 sm:p-5"><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">{editing ? "Editar ingreso" : "Nuevo ingreso"}</h2><p className="text-sm text-muted-foreground">Al registrar una disposición, el siguiente acumulado comienza sin ese residuo.</p></div>{editing && <Button variant="outline" onClick={() => { setEditing(null); setForm(emptyForm()); }}>Cancelar edición</Button>}</div>
        <form onSubmit={saveRecord} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className="text-sm">Fecha de ingreso<Input className="mt-1" type="date" value={form.entry_date} onChange={(e) => setForm({ ...form, entry_date: e.target.value })} required /></label>
          <label className="text-sm">N° RESPEL<Input className="mt-1" list="hazardous-waste-codes" value={form.respel_code} onChange={(e) => setForm({ ...form, respel_code: e.target.value })} /></label>
          <label className="text-sm">Nombre RESPEL<Input className="mt-1" list="hazardous-waste-names" value={form.waste_name} onChange={(e) => setForm({ ...form, waste_name: e.target.value })} required /></label>
          <label className="text-sm">Peligrosidad<Input className="mt-1" list="hazardous-waste-hazards" value={form.hazard} onChange={(e) => setForm({ ...form, hazard: e.target.value })} /></label>
          <label className="text-sm">Origen<Input className="mt-1" list="hazardous-waste-origins" value={form.origin} onChange={(e) => setForm({ ...form, origin: e.target.value })} /></label>
          <label className="text-sm">Cantidad de unidades<Input className="mt-1" type="number" min="1" step="1" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} placeholder="Dejar vacío si no está disponible" /></label>
          <label className="text-sm">Nombre de quien entrega<Input className="mt-1" list="hazardous-waste-people" value={form.delivered_by} onChange={(e) => setForm({ ...form, delivered_by: e.target.value })} /></label>
          <label className="text-sm">Fecha de transporte y disposición<Input className="mt-1" type="date" value={form.disposal_date} onChange={(e) => setForm({ ...form, disposal_date: e.target.value })} /></label>
          <label className="text-sm">Nombre de gestor<Input className="mt-1" list="hazardous-waste-people" value={form.manager} onChange={(e) => setForm({ ...form, manager: e.target.value })} /></label>
          <datalist id="hazardous-waste-codes">{options.codes.map((value) => <option key={value} value={value} />)}</datalist>
          <datalist id="hazardous-waste-names">{options.wasteNames.map((value) => <option key={value} value={value} />)}</datalist>
          <datalist id="hazardous-waste-hazards">{options.hazards.map((value) => <option key={value} value={value} />)}</datalist>
          <datalist id="hazardous-waste-origins">{options.origins.map((value) => <option key={value} value={value} />)}</datalist>
          <datalist id="hazardous-waste-people">{options.people.map((value) => <option key={value} value={value} />)}</datalist>
          <div className="flex items-end sm:col-span-2 lg:col-span-3"><Button disabled={busy}>{busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : editing ? <Save className="mr-2 h-4 w-4" /> : <Plus className="mr-2 h-4 w-4" />}{editing ? "Guardar cambios" : "Registrar ingreso"}</Button></div>
        </form>
      </Card>

      <Card className="p-4 sm:p-5"><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">Historial</h2><p className="text-sm text-muted-foreground">{storedCount} ingresos sin disposición registrada.</p></div><div className="flex flex-wrap gap-2"><Input className="w-56" placeholder="Buscar residuo, código u origen" value={search} onChange={(e) => setSearch(e.target.value)} /><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={storedOnly} onChange={(e) => setStoredOnly(e.target.checked)} />Solo almacenados</label><Button variant="outline" onClick={() => void load()}><RefreshCw className="mr-2 h-4 w-4" />Actualizar</Button>{storedCount > 0 && <Button variant="outline" className="border-amber-300 text-amber-900 hover:bg-amber-50" onClick={beginBulkDisposal}>Retirar todos ({storedCount})</Button>}</div></div>
        {bulkDisposalOpen && <form onSubmit={registerBulkDisposal} className="mb-4 rounded-lg border border-red-300 bg-red-50 p-4"><h3 className="font-semibold text-red-900">Retirar todos los residuos almacenados</h3><p className="mb-3 mt-1 text-sm text-red-900">Esta acción marcará como retirados los {storedCount} ingresos actualmente almacenados, en todos los años y sin importar la búsqueda o los filtros. Se recalculará el acumulado y los cambios quedarán en cola para Google Sheets. Confirma que el retiro físico de todos ya ocurrió.</p><div className="flex flex-wrap items-end gap-3"><label className="text-sm">Fecha de retiro<Input className="mt-1" type="date" value={disposalDate} onChange={(e) => setDisposalDate(e.target.value)} required /></label><label className="text-sm">Gestor<Input className="mt-1" list="hazardous-waste-people" value={disposalManager} onChange={(e) => setDisposalManager(e.target.value)} required /></label><Button disabled={busy || !disposalManager.trim()} className="bg-red-700 hover:bg-red-800">{busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Check className="mr-2 h-4 w-4" />}{busy ? "Registrando retiros…" : `Confirmar retiro de ${storedCount}`}</Button><Button type="button" variant="outline" disabled={busy} onClick={() => setBulkDisposalOpen(false)}>Cancelar</Button></div></form>}
        {disposing && <form onSubmit={registerDisposal} className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-4"><h3 className="font-semibold">Registrar retiro de {disposing.waste_name}</h3><p className="mb-3 mt-1 text-sm text-muted-foreground">Se marcarán como retirados todos los ingresos de este residuo que sigan almacenados hasta la fecha indicada. El acumulado se reiniciará para los ingresos posteriores.</p><div className="flex flex-wrap items-end gap-3"><label className="text-sm">Fecha de retiro<Input className="mt-1" type="date" min={disposing.entry_date} value={disposalDate} onChange={(e) => setDisposalDate(e.target.value)} required /></label><label className="text-sm">Gestor<Input className="mt-1" list="hazardous-waste-people" value={disposalManager} onChange={(e) => setDisposalManager(e.target.value)} required /></label><Button disabled={busy || !disposalManager.trim()}>{busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Check className="mr-2 h-4 w-4" />}{busy ? "Guardando retiro…" : "Confirmar retiro"}</Button><Button type="button" variant="outline" disabled={busy} onClick={() => setDisposing(null)}>Cancelar</Button></div></form>}
        {!visibleRecords.length ? <p className="p-8 text-center text-muted-foreground">No hay ingresos para mostrar.</p> : <div className="overflow-x-auto"><table className="w-full min-w-[1050px] text-left text-sm"><thead><tr className="border-b text-muted-foreground">{["Ingreso", "N° / Residuo", "Peligrosidad / origen", "Unidades ingresadas", "Unidades almacenadas", "Entrega", "Disposición / gestor", "Drive", ""].map((h) => <th key={h} className="px-3 py-3 font-medium">{h}</th>)}</tr></thead><tbody>{visibleRecords.map((row) => <tr key={row.id} className="border-b last:border-0"><td className="px-3 py-3">{dateText(row.entry_date)}</td><td className="px-3 py-3"><div className="font-medium">{row.respel_code || "—"}</div><div>{row.waste_name}</div></td><td className="px-3 py-3">{row.hazard || "—"}<div className="text-xs text-muted-foreground">{row.origin || "—"}</div></td><td className="px-3 py-3">{amount(row.quantity, "UNIDADES")}</td><td className="px-3 py-3 font-medium">{amount(row.accumulated_quantity, "UNIDADES")}</td><td className="px-3 py-3">{row.delivered_by || "—"}</td><td className="px-3 py-3">{row.disposal_date ? dateText(row.disposal_date) : <span className="text-amber-700">Almacenado</span>}<div className="text-xs text-muted-foreground">{row.manager || "—"}</div></td><td className="px-3 py-3"><span className={`inline-flex items-center gap-1 ${row.sync_status === "SYNCED" ? "text-emerald-700" : row.sync_status === "FAILED" ? "text-red-700" : "text-amber-700"}`}>{row.sync_status === "SYNCED" ? <Check className="h-3 w-3" /> : row.sync_status === "FAILED" ? <AlertCircle className="h-3 w-3" /> : <Loader2 className="h-3 w-3 animate-spin" />}{row.sync_status === "SYNCED" ? "Sincronizado" : row.sync_status === "FAILED" ? "Error" : "Pendiente"}</span>{row.sync_error && <div className="max-w-40 text-xs text-red-600">{row.sync_error}</div>}</td><td className="px-3 py-3"><div className="flex gap-1"><Button type="button" size="sm" variant="outline" onClick={() => editRecord(row)}>Editar</Button>{!row.disposal_date && <Button type="button" size="sm" variant="outline" onClick={() => beginDisposal(row)}>Registrar retiro</Button>}{row.sync_status === "FAILED" && <Button type="button" size="sm" variant="outline" aria-label="Reintentar" onClick={() => void retry(row.id)}><RefreshCw className="h-3.5 w-3.5" /></Button>}</div></td></tr>)}</tbody></table></div>}
      </Card>
    </>}
  </Shell>;
}
