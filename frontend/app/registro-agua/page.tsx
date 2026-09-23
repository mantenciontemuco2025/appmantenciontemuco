"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, BarChart3, Check, Clock3, Download, Droplets, Loader2, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PageLoading } from "@/components/ui/page-loading";
import { useAuth } from "@/lib/auth";
import { ApiError, api } from "@/lib/api";
import type { WaterRegisterAccess } from "@/lib/types";

type Meter = { key: string; label: string };
type Baseline = { meter_key: string; final_reading: string; reading_date: string; source_row: number };
type MeterReading = { meter_key: string; initial_reading: string; final_reading: string; volume_m3: string };
type DqoSample = { id?: number; date: string; time: string; pool: string; mg_l: string };
type WaterRecord = {
  id: number;
  record_date: string;
  discharge_flow_m3: string | null;
  ph_plc: string | null;
  ph_discharge: string | null;
  discharge_temp_c: string | null;
  dqo_date: string | null;
  dqo_time: string | null;
  dqo_pool: string | null;
  dqo_mg_l: string | null;
  dqo_samples: DqoSample[];
  sync_status: string;
  sync_error: string | null;
  sheet_row: number | null;
  meter_readings: MeterReading[];
};
type WaterData = { records: WaterRecord[]; baselines: Baseline[]; meters: Meter[]; latest_readings: Record<string, string>; latest_reading_dates: Record<string, string> };
type HistoricalMeter = { meter_key: string; label: string; initial_reading: string | null; final_reading: string | null; volume_m3: string | null };
type HistoricalDqo = { date: string; time: string | null; pool: string | null; mg_l: string | null };
type HistoricalRow = { sheet_row: number; record_date: string; discharge_flow_m3: string | null; ph_plc: string | null; ph_discharge: string | null; discharge_temp_c: string | null; meters: HistoricalMeter[]; dqo: HistoricalDqo | null };
type HistoricalData = { from_date: string; to_date: string; rows: HistoricalRow[] };
type FormState = {
  record_date: string;
  discharge_flow_m3: string;
  ph_plc: string;
  ph_discharge: string;
  discharge_temp_c: string;
  meter_final_readings: Record<string, string>;
  dqo_samples: DqoSample[];
};

const today = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
};
const emptyForm = (): FormState => ({
  record_date: today(), discharge_flow_m3: "", ph_plc: "", ph_discharge: "", discharge_temp_c: "",
  meter_final_readings: {}, dqo_samples: [{ date: today(), time: "", pool: "", mg_l: "" }],
});
const emptyDqoSample = (): DqoSample => ({ date: today(), time: "", pool: "", mg_l: "" });
const fmtDate = (date: string) => date ? new Date(`${date}T12:00:00`).toLocaleDateString("es-CL") : "—";
const numberText = (value: string | number | null | undefined) => value === null || value === undefined || value === "" ? "—" : Number(value).toLocaleString("es-CL", { maximumFractionDigits: 3 });

type ChartSeries = { key: string; label: string; color: string; values: (number | null)[] };
type WaterChartData = { labels: string[]; series: ChartSeries[] };

function numericValue(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function firstNumber(rows: HistoricalRow[], field: keyof Pick<HistoricalRow, "discharge_flow_m3" | "ph_plc" | "ph_discharge" | "discharge_temp_c">) {
  for (const row of rows) {
    const value = numericValue(row[field]);
    if (value !== null) return value;
  }
  return null;
}

function average(values: (number | null)[]) {
  const valid = values.filter((value): value is number => value !== null);
  return valid.length ? valid.reduce((total, value) => total + value, 0) / valid.length : null;
}

function buildWaterChartData(rows: HistoricalRow[]): WaterChartData {
  const dates = Array.from(new Set(rows.map((row) => row.record_date))).sort();
  const rowsByDate = new Map(dates.map((date) => [date, rows.filter((row) => row.record_date === date)]));
  const valuesByDate = (reader: (dateRows: HistoricalRow[]) => number | null) =>
    dates.map((date) => reader(rowsByDate.get(date) ?? []));

  const meterMap = new Map<string, string>();
  for (const row of rows) {
    for (const meter of row.meters) meterMap.set(meter.meter_key, meter.label);
  }

  const series: ChartSeries[] = [
    { key: "flow", label: "Caudal descarga (m³)", color: "#0284c7", values: valuesByDate((dateRows) => firstNumber(dateRows, "discharge_flow_m3")) },
    { key: "ph-plc", label: "pH PLC", color: "#7c3aed", values: valuesByDate((dateRows) => firstNumber(dateRows, "ph_plc")) },
    { key: "ph-discharge", label: "pH descarga", color: "#db2777", values: valuesByDate((dateRows) => firstNumber(dateRows, "ph_discharge")) },
    { key: "temperature", label: "Temperatura descarga (°C)", color: "#ea580c", values: valuesByDate((dateRows) => firstNumber(dateRows, "discharge_temp_c")) },
    ...Array.from(meterMap.entries()).map(([meterKey, label], index) => ({
      key: `meter-${meterKey}`,
      label: `Volumen ${label} (m³)`,
      color: ["#059669", "#0891b2", "#65a30d", "#ca8a04", "#9333ea", "#e11d48"][index % 6],
      values: valuesByDate((dateRows) => {
        for (const row of dateRows) {
          const value = numericValue(row.meters.find((meter) => meter.meter_key === meterKey)?.volume_m3);
          if (value !== null) return value;
        }
        return null;
      }),
    })),
    { key: "dqo", label: "DQO (mg/L)", color: "#475569", values: valuesByDate((dateRows) => average(dateRows.map((row) => numericValue(row.dqo?.mg_l)))) },
  ];

  return { labels: dates.map(fmtDate), series };
}

function WaterLineChart({ title, labels, series }: { title: string; labels: string[]; series: ChartSeries[] }) {
  const visibleSeries = series.filter((item) => item.values.some((value) => value !== null));
  if (!visibleSeries.length || !labels.length) return null;

  const allValues = visibleSeries.flatMap((item) => item.values).filter((value): value is number => value !== null);
  let min = Math.min(...allValues);
  let max = Math.max(...allValues);
  if (min === max) {
    const padding = Math.max(Math.abs(min) * 0.1, 1);
    min -= padding;
    max += padding;
  } else {
    const padding = (max - min) * 0.1;
    min -= padding;
    max += padding;
  }

  const width = 900;
  const height = 260;
  const left = 48;
  const right = 18;
  const top = 18;
  const bottom = 42;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const x = (index: number) => labels.length === 1 ? left + plotWidth / 2 : left + (index / (labels.length - 1)) * plotWidth;
  const y = (value: number) => top + ((max - value) / (max - min)) * plotHeight;
  const labelStep = Math.max(1, Math.ceil(labels.length / 6));
  const yLabels = Array.from({ length: 5 }, (_, index) => max - ((max - min) * index) / 4);

  function pathSegments(values: (number | null)[]) {
    const paths: string[] = [];
    let current: string[] = [];
    values.forEach((value, index) => {
      if (value === null) {
        if (current.length) paths.push(current.join(" "));
        current = [];
        return;
      }
      current.push(`${current.length ? "L" : "M"} ${x(index).toFixed(2)} ${y(value).toFixed(2)}`);
    });
    if (current.length) paths.push(current.join(" "));
    return paths;
  }

  return (
    <div className="rounded-lg border bg-muted/10 p-3 sm:p-4">
      <h4 className="mb-2 text-sm font-semibold">{title}</h4>
      <svg className="h-auto w-full" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
        {yLabels.map((value, index) => <g key={`y-${index}`}>
          <line x1={left} x2={width - right} y1={y(value)} y2={y(value)} stroke="#e2e8f0" strokeWidth="1" />
          <text x={left - 8} y={y(value) + 4} textAnchor="end" fontSize="11" fill="#64748b">{value.toLocaleString("es-CL", { maximumFractionDigits: 1 })}</text>
        </g>)}
        <line x1={left} x2={left} y1={top} y2={height - bottom} stroke="#cbd5e1" />
        <line x1={left} x2={width - right} y1={height - bottom} y2={height - bottom} stroke="#cbd5e1" />
        {visibleSeries.map((item) => <g key={item.key}>
          {pathSegments(item.values).map((path, index) => <path key={`${item.key}-path-${index}`} d={path} fill="none" stroke={item.color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />)}
          {item.values.map((value, index) => value === null ? null : <circle key={`${item.key}-${index}`} cx={x(index)} cy={y(value)} r="3.5" fill={item.color}>
            <title>{`${item.label}: ${value.toLocaleString("es-CL", { maximumFractionDigits: 3 })} · ${labels[index]}`}</title>
          </circle>)}
        </g>)}
        {labels.map((label, index) => index % labelStep === 0 || index === labels.length - 1 ? <text key={`x-${index}`} x={x(index)} y={height - 14} textAnchor="middle" fontSize="11" fill="#64748b">{label}</text> : null)}
      </svg>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {visibleSeries.map((item) => <span key={`legend-${item.key}`}><span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />{item.label}</span>)}
      </div>
    </div>
  );
}

function syncLabel(status: string) {
  if (status === "SYNCED") return { text: "Sincronizado", tone: "text-emerald-700 bg-emerald-50" };
  if (status === "SYNCING" || status === "PENDING") return { text: status === "SYNCING" ? "Enviando a Sheets…" : "Pendiente de sincronizar", tone: "text-amber-700 bg-amber-50" };
  return { text: "Error de sincronización", tone: "text-red-700 bg-red-50" };
}

export default function WaterRegisterPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<WaterData | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [initializing, setInitializing] = useState(false);
  const [refreshingLatest, setRefreshingLatest] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [historyFrom, setHistoryFrom] = useState("");
  const [historyTo, setHistoryTo] = useState("");
  const [history, setHistory] = useState<HistoricalData | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyExporting, setHistoryExporting] = useState(false);
  const [importingDate, setImportingDate] = useState("");
  const waterAccess: WaterRegisterAccess = user?.role === "ADMIN"
    ? "EDIT"
    : user?.water_register_access === "VIEW" || user?.water_register_access === "EDIT"
      ? user.water_register_access
      : user?.water_register_access === "NONE"
        ? "NONE"
        : user?.can_manage_water_register || user?.role === "SUPERVISOR" ? "EDIT" : "NONE";
  const canViewWater = waterAccess !== "NONE";
  const canManageWater = waterAccess === "EDIT";
  const hasBaselines = (data?.baselines.length ?? 0) === (data?.meters.length ?? -1) && !!data?.meters.length;

  useEffect(() => {
    if (!loading && user && !canViewWater) {
      router.replace("/dashboard");
    }
  }, [loading, user, canViewWater, router]);

  const load = useCallback(async () => {
    const result = await api.get<WaterData>("/api/water-register");
    setData(result);
    return result;
  }, []);

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    load().catch((err: Error) => setError(err.message || "No se pudo cargar el registro."));
  }, [user, load]);

  useEffect(() => {
    if (!data?.records.some((record) => record.sync_status === "PENDING" || record.sync_status === "SYNCING")) return;
    const timer = window.setInterval(() => load().catch(() => undefined), 3000);
    return () => window.clearInterval(timer);
  }, [data?.records, load]);

  function openingFor(meterKey: string, recordDate: string) {
    const currentRecord = data?.records.find((row) => row.record_date === recordDate);
    const currentOpening = currentRecord?.meter_readings.find((item) => item.meter_key === meterKey)?.initial_reading;
    if (currentOpening) return currentOpening;
    const prior = (data?.records ?? [])
      .filter((row) => row.record_date < recordDate)
      .sort((a, b) => b.record_date.localeCompare(a.record_date));
    const priorReading = prior
      .map((row) => ({ date: row.record_date, value: row.meter_readings.find((item) => item.meter_key === meterKey)?.final_reading }))
      .find((item) => item.value !== undefined);
    const latestValue = data?.latest_readings[meterKey];
    const latestDate = data?.latest_reading_dates[meterKey];
    if (latestValue && latestDate && latestDate < recordDate && (!priorReading || latestDate >= priorReading.date)) {
      return latestValue;
    }
    if (priorReading?.value !== undefined) return priorReading.value;
    const baseline = data?.baselines.find((item) => item.meter_key === meterKey);
    if (latestValue && (!latestDate || latestDate < recordDate)) return latestValue;
    if (baseline && baseline.reading_date < recordDate) return baseline.final_reading;
    return "—";
  }

  function editRecord(record: WaterRecord) {
    const readings: Record<string, string> = {};
    for (const reading of record.meter_readings) readings[reading.meter_key] = reading.final_reading;
    setForm({
      record_date: record.record_date,
      discharge_flow_m3: record.discharge_flow_m3 ?? "",
      ph_plc: record.ph_plc ?? "",
      ph_discharge: record.ph_discharge ?? "",
      discharge_temp_c: record.discharge_temp_c ?? "",
      meter_final_readings: readings,
      dqo_samples: record.dqo_samples?.length
        ? record.dqo_samples.map((sample) => ({ ...sample }))
        : record.dqo_mg_l !== null
          ? [{ id: undefined, date: record.dqo_date ?? record.record_date, time: record.dqo_time ?? "", pool: record.dqo_pool ?? "", mg_l: record.dqo_mg_l }]
          : [emptyDqoSample()],
    });
    setEditingId(record.id);
    setError("");
    setMessage("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function updateDqoSample(index: number, changes: Partial<DqoSample>) {
    setForm({
      ...form,
      dqo_samples: form.dqo_samples.map((sample, currentIndex) => currentIndex === index ? { ...sample, ...changes } : sample),
    });
  }

  function addDqoSample() {
    setForm({ ...form, dqo_samples: [...form.dqo_samples, emptyDqoSample()] });
  }

  function removeDqoSample(index: number) {
    const samples = form.dqo_samples.filter((_, currentIndex) => currentIndex !== index);
    setForm({ ...form, dqo_samples: samples.length ? samples : [emptyDqoSample()] });
  }

  async function initialize() {
    setInitializing(true); setError(""); setMessage("");
    try {
      const result = await api.post<{ initialized: number; baselines: number; message: string }>("/api/water-register/initialize-from-sheet");
      setMessage(`${result.message} ${result.initialized} lecturas iniciales importadas.`);
      await load();
    } catch (err) { setError((err as Error).message || "No se pudieron importar las lecturas."); }
    finally { setInitializing(false); }
  }

  async function refreshLatestReadings() {
    setRefreshingLatest(true); setError(""); setMessage("");
    try {
      const result = await api.post<{ updated: number; inserted: number; readings: number; message: string }>("/api/water-register/refresh-latest-readings", {});
      await load();
      setMessage(`${result.message} ${result.updated + result.inserted} medidores actualizados.`);
    } catch (err) { setError((err as Error).message || "No se pudieron actualizar las últimas lecturas."); }
    finally { setRefreshingLatest(false); }
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError(""); setMessage("");
    const dqoStarted = form.dqo_samples.filter((sample) => sample.time || sample.pool || sample.mg_l);
    const incompleteDqo = dqoStarted.some((sample) => !sample.date || !sample.time || !sample.pool.trim() || !sample.mg_l);
    if (incompleteDqo) {
      setError("Cada análisis DQO debe tener fecha, hora, piscina y resultado mg/L."); setSaving(false); return;
    }
    const payload = {
      record_date: form.record_date,
      discharge_flow_m3: form.discharge_flow_m3 || null,
      ph_plc: form.ph_plc || null,
      ph_discharge: form.ph_discharge || null,
      discharge_temp_c: form.discharge_temp_c || null,
      meter_final_readings: Object.fromEntries(Object.entries(form.meter_final_readings).map(([key, value]) => [key, value || null])),
      dqo_samples: dqoStarted.map((sample) => ({ ...sample, pool: sample.pool.trim() })),
    };
    try {
      await (editingId
        ? api.put<WaterRecord>(`/api/water-register/${form.record_date}`, payload)
        : api.post<WaterRecord>("/api/water-register", payload));
      setEditingId(null); setForm(emptyForm());
      setMessage("Registro guardado. La planilla se sincroniza en segundo plano.");
      await load();
    } catch (err) {
      const existing = data?.records.find((record) => record.record_date === form.record_date);
      if (!editingId && err instanceof ApiError && err.status === 409 && existing) {
        const entered = form;
        editRecord(existing);
        setForm((current) => ({
          ...current,
          discharge_flow_m3: entered.discharge_flow_m3 || current.discharge_flow_m3,
          ph_plc: entered.ph_plc || current.ph_plc,
          ph_discharge: entered.ph_discharge || current.ph_discharge,
          discharge_temp_c: entered.discharge_temp_c || current.discharge_temp_c,
          meter_final_readings: {
            ...current.meter_final_readings,
            ...Object.fromEntries(Object.entries(entered.meter_final_readings).filter(([, value]) => value)),
          },
          dqo_samples: entered.dqo_samples.some((sample) => sample.time || sample.pool || sample.mg_l)
            ? entered.dqo_samples
            : current.dqo_samples,
        }));
        setMessage("Ese día ya existía. Se cargó en modo edición; revisa los datos y guarda los cambios.");
      } else {
        setError((err as Error).message || "No se pudo guardar el registro.");
      }
    }
    finally { setSaving(false); }
  }

  async function retrySync(recordId: number) {
    try {
      await api.post(`/api/water-register/${recordId}/retry-sync`);
      setMessage("Sincronización puesta nuevamente en cola.");
      await load();
    } catch (err) { setError((err as Error).message || "No se pudo reintentar la sincronización."); }
  }

  async function consultHistory(event: FormEvent) {
    event.preventDefault();
    if (!historyFrom || !historyTo) {
      setError("Selecciona las fechas desde y hasta.");
      return;
    }
    setHistoryLoading(true); setError(""); setMessage("");
    try {
      const params = new URLSearchParams({ from: historyFrom, to: historyTo });
      setHistory(await api.get<HistoricalData>(`/api/water-register/history?${params.toString()}`));
    } catch (err) {
      setError((err as Error).message || "No se pudo consultar el histórico.");
    } finally { setHistoryLoading(false); }
  }

  async function downloadHistory() {
    if (!historyFrom || !historyTo) {
      setError("Selecciona las fechas desde y hasta para descargar el rango.");
      return;
    }
    setHistoryExporting(true); setError(""); setMessage("");
    try {
      const params = new URLSearchParams({ from: historyFrom, to: historyTo });
      const blob = await api.getBlob(`/api/water-register/history/export?${params.toString()}`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `registro_agua_${historyFrom.replaceAll("-", "")}_${historyTo.replaceAll("-", "")}.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setMessage("Descarga generada con las fechas seleccionadas.");
    } catch (err) { setError((err as Error).message || "No se pudo descargar el rango seleccionado."); }
    finally { setHistoryExporting(false); }
  }

  async function importHistoricalDay(recordDate: string) {
    setImportingDate(recordDate); setError(""); setMessage("");
    try {
      const record = await api.post<WaterRecord>(
        `/api/water-register/import-day?date=${encodeURIComponent(recordDate)}`,
        {},
      );
      await load();
      editRecord(record);
      setMessage("Día importado. Puedes completar o agregar muestras DQO sin duplicar la fecha.");
    } catch (err) {
      setError((err as Error).message || "No se pudo importar ese día.");
    } finally { setImportingDate(""); }
  }

  const chartData = history ? buildWaterChartData(history.rows) : null;

  if (loading || !user) return <PageLoading message={loading ? "Validando sesión…" : "Redirigiendo al inicio de sesión…"} />;

  return (
        <Shell fullName={user.full_name} role={user.role} waterRegisterAccess={waterAccess} onLogout={logout}>
      <div className="mb-6 flex items-start gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-sky-100 text-sky-700"><Droplets className="h-6 w-6" /></span>
        <div><h1 className="text-2xl font-bold">Planta de RILES</h1><p className="text-muted-foreground">Lecturas diarias, medidores y control de DQO.</p></div>
      </div>

      {(error || message) && <div className={`mb-4 rounded-lg border p-3 text-sm ${error ? "border-red-200 bg-red-50 text-red-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error || message}</div>}

      {canManageWater && !hasBaselines && (
        <Card className="mb-5 border-amber-200 bg-amber-50/70 p-4">
          <h2 className="font-semibold">Configuración inicial requerida</h2>
          <p className="mt-1 text-sm text-muted-foreground">Importa desde la copia de la planilla la última lectura válida de cada medidor. Se ignoran los ceros de las filas futuras.</p>
          {user.role === "ADMIN" ? <Button className="mt-3" onClick={initialize} disabled={initializing}>{initializing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />} Importar lecturas iniciales</Button> : <p className="mt-3 text-sm font-medium">Solicita al administrador realizar esta inicialización única.</p>}
        </Card>
      )}

      {canManageWater && hasBaselines && (
        <Card className="mb-6 p-4 sm:p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div><h2 className="text-lg font-semibold">{editingId ? "Editar registro diario" : "Nuevo registro diario"}</h2><p className="text-sm text-muted-foreground">Una fila por día. Las columnas de volumen las calcula la hoja.</p></div>
            {editingId && <Button variant="outline" onClick={() => { setEditingId(null); setForm(emptyForm()); }}>Cancelar edición</Button>}
          </div>
          <form onSubmit={submit} className="space-y-6">
            <section>
              <h3 className="mb-3 font-semibold">Datos generales</h3>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                <label className="text-sm">Fecha<input className="mt-1 h-11 w-full rounded-md border bg-background px-3" type="date" required value={form.record_date} onChange={(e) => setForm({ ...form, record_date: e.target.value })} disabled={!!editingId} /></label>
                <label className="text-sm">Caudal descarga (m³)<Input className="mt-1" type="number" min="0" step="0.001" value={form.discharge_flow_m3} onChange={(e) => setForm({ ...form, discharge_flow_m3: e.target.value })} /></label>
                <label className="text-sm">pH PLC<Input className="mt-1" type="number" min="0" max="14" step="0.01" value={form.ph_plc} onChange={(e) => setForm({ ...form, ph_plc: e.target.value })} /></label>
                <label className="text-sm">pH descarga<Input className="mt-1" type="number" min="0" max="14" step="0.01" value={form.ph_discharge} onChange={(e) => setForm({ ...form, ph_discharge: e.target.value })} /></label>
                <label className="text-sm">Temperatura descarga (°C)<Input className="mt-1" type="number" step="0.01" value={form.discharge_temp_c} onChange={(e) => setForm({ ...form, discharge_temp_c: e.target.value })} /></label>
              </div>
            </section>

            <section>
              <div className="mb-3 flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-semibold">Medidores</h3><p className="text-sm text-muted-foreground">La lectura inicial se toma de la última lectura disponible; ingresa solo la final si hubo medición.</p></div><Button type="button" variant="outline" size="sm" onClick={refreshLatestReadings} disabled={refreshingLatest}>{refreshingLatest ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}Actualizar últimas lecturas</Button></div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {(data?.meters ?? []).map((meter) => <div key={meter.key} className="rounded-lg border bg-muted/20 p-3">
                  <p className="mb-2 text-sm font-medium">{meter.label}</p>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="text-xs text-muted-foreground">Inicial<Input className="mt-1 h-10 bg-muted/50 text-foreground" readOnly value={openingFor(meter.key, form.record_date)} /></label>
                    <label className="text-xs text-muted-foreground">Final<Input className="mt-1 h-10" type="number" min="0" max="9999999999999.999" step="0.001" value={form.meter_final_readings[meter.key] ?? ""} onChange={(e) => setForm({ ...form, meter_final_readings: { ...form.meter_final_readings, [meter.key]: e.target.value } })} /></label>
                  </div>
                </div>)}
              </div>
            </section>

            <section>
              <h3 className="mb-1 font-semibold">Análisis de DQO <span className="font-normal text-muted-foreground">(opcional, varias muestras por día)</span></h3>
              <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                <div><h3 className="font-semibold">Análisis de DQO</h3><p className="text-sm text-muted-foreground">Puedes registrar varias muestras del mismo día. Solo se escriben las columnas AD:AG de la planilla.</p></div>
                <Button type="button" variant="outline" size="sm" onClick={addDqoSample}><Plus className="mr-1 h-4 w-4" />Agregar muestra</Button>
              </div>
              <div className="mt-3 space-y-3">
                {form.dqo_samples.map((sample, index) => <div key={sample.id ?? `new-${index}`} className="rounded-lg border bg-muted/20 p-3">
                  <div className="mb-2 flex items-center justify-between"><span className="text-sm font-medium">Muestra {index + 1}</span><Button type="button" variant="ghost" size="sm" onClick={() => removeDqoSample(index)} aria-label={`Eliminar muestra ${index + 1}`}><Trash2 className="h-4 w-4 text-red-600" /></Button></div>
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <label className="text-sm">Fecha muestra<input className="mt-1 h-11 w-full rounded-md border bg-background px-3" type="date" value={sample.date} onChange={(e) => updateDqoSample(index, { date: e.target.value })} /></label>
                    <label className="text-sm">Hora de muestreo<Input className="mt-1" type="time" value={sample.time} onChange={(e) => updateDqoSample(index, { time: e.target.value })} /></label>
                    <label className="text-sm">Piscina<Input className="mt-1" value={sample.pool} onChange={(e) => updateDqoSample(index, { pool: e.target.value })} placeholder="1, 2 o 3" /></label>
                    <label className="text-sm">DQO (mg/L)<Input className="mt-1" type="number" min="0" step="0.001" value={sample.mg_l} onChange={(e) => updateDqoSample(index, { mg_l: e.target.value })} /></label>
                  </div>
                </div>)}
              </div>
            </section>
            <div className="flex justify-end"><Button type="submit" disabled={saving}>{saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}{editingId ? "Guardar cambios" : "Guardar registro"}</Button></div>
          </form>
        </Card>
      )}

      <Card className="mb-6 p-4 sm:p-6">
        <div className="mb-4"><h2 className="text-lg font-semibold">Consultar histórico de la planilla</h2><p className="text-sm text-muted-foreground">Consulta uno o varios días directamente desde Google Sheets. Si un día ya fue llenado manualmente, puedes importarlo una sola vez para editarlo y agregar muestras DQO desde la app.</p></div>
        <form onSubmit={consultHistory} className="flex flex-wrap items-end gap-3">
          <label className="text-sm">Desde<input className="mt-1 h-11 rounded-md border bg-background px-3" type="date" value={historyFrom} onChange={(e) => setHistoryFrom(e.target.value)} required /></label>
          <label className="text-sm">Hasta<input className="mt-1 h-11 rounded-md border bg-background px-3" type="date" value={historyTo} onChange={(e) => setHistoryTo(e.target.value)} required /></label>
          <Button type="submit" disabled={historyLoading}>{historyLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <BarChart3 className="mr-2 h-4 w-4" />}{historyLoading ? "Consultando..." : "Consultar y graficar"}</Button>
          <Button type="button" variant="outline" onClick={downloadHistory} disabled={historyExporting}>{historyExporting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}{historyExporting ? "Generando..." : "Descargar Excel"}</Button>
        </form>
        {history && <div className="mt-5 space-y-3">
          <p className="text-sm font-medium">{history.rows.length ? `${history.rows.length} fila(s) encontradas` : "No hay datos registrados en ese rango."}</p>
          {chartData && chartData.series.some((item) => item.values.some((value) => value !== null)) && <section className="mb-5 rounded-xl border bg-sky-50/30 p-3 sm:p-5">
            <div className="mb-4 flex items-start gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sky-100 text-sky-700"><BarChart3 className="h-5 w-5" /></span>
              <div><h3 className="font-semibold">Gráficos del rango seleccionado</h3><p className="text-sm text-muted-foreground">Cada punto representa un día con datos. Los días sin una medición quedan sin punto.</p></div>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <WaterLineChart title="Caudal de descarga" labels={chartData.labels} series={chartData.series.filter((item) => item.key === "flow")} />
              <WaterLineChart title="pH" labels={chartData.labels} series={chartData.series.filter((item) => item.key === "ph-plc" || item.key === "ph-discharge")} />
              <WaterLineChart title="Temperatura de descarga" labels={chartData.labels} series={chartData.series.filter((item) => item.key === "temperature")} />
              <WaterLineChart title="Volumen diario por medidor" labels={chartData.labels} series={chartData.series.filter((item) => item.key.startsWith("meter-"))} />
              <WaterLineChart title="DQO promedio por día" labels={chartData.labels} series={chartData.series.filter((item) => item.key === "dqo")} />
            </div>
          </section>}
          {history.rows.map((row, index) => {
            const importedRecord = data?.records.find((record) => record.record_date === row.record_date);
            const alreadyImported = Boolean(importedRecord);
            return <div key={row.sheet_row} className="rounded-lg border bg-muted/20 p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-semibold">{fmtDate(row.record_date)}</span><div className="flex items-center gap-2"><span className="text-xs text-muted-foreground">Fila {row.sheet_row}</span>{canManageWater && history.rows.findIndex((candidate) => candidate.record_date === row.record_date) === index && <Button type="button" variant="outline" size="sm" onClick={() => alreadyImported && importedRecord ? editRecord(importedRecord) : importHistoricalDay(row.record_date)} disabled={importingDate === row.record_date}>{importingDate === row.record_date ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : alreadyImported ? <Save className="mr-1 h-3.5 w-3.5" /> : <Download className="mr-1 h-3.5 w-3.5" />}{importingDate === row.record_date ? "Importando..." : alreadyImported ? "Editar día" : "Importar día"}</Button>}</div></div>
              <p className="mt-1 text-muted-foreground">Caudal: {numberText(row.discharge_flow_m3)} m³ · pH PLC: {numberText(row.ph_plc)} · pH descarga: {numberText(row.ph_discharge)} · Temp.: {numberText(row.discharge_temp_c)} °C</p>
              {row.meters.length > 0 && <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{row.meters.map((meter) => <div key={`${row.sheet_row}-${meter.meter_key}`} className="rounded-md bg-background px-3 py-2"><p className="font-medium">{meter.label}</p><p className="text-muted-foreground">{numberText(meter.initial_reading)} → {numberText(meter.final_reading)}</p><p className="font-medium text-sky-700">Volumen: {numberText(meter.volume_m3)} m³</p></div>)}</div>}
              {row.dqo && <p className="mt-3 text-muted-foreground">DQO: {fmtDate(row.dqo.date)} · {row.dqo.time || "sin hora"} · Piscina {row.dqo.pool || "—"} · {numberText(row.dqo.mg_l)} mg/L</p>}
            </div>;
          })}
        </div>}
      </Card>

      {!canManageWater && <Card className="mb-5 p-4 text-sm text-muted-foreground">Tienes acceso de solo consulta. No puedes registrar ni editar datos.</Card>}

      <section>
        <h2 className="mb-3 text-lg font-semibold">Registros recientes</h2>
        {!data?.records.length ? <Card className="p-8 text-center text-muted-foreground">Aún no hay registros diarios.</Card> : <div className="space-y-3">
          {data.records.map((record) => {
            const sync = syncLabel(record.sync_status);
            return <Card key={record.id} className="p-4 sm:p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold">{fmtDate(record.record_date)}</h3><span className={`rounded-full px-2.5 py-1 text-xs font-medium ${sync.tone}`}>{record.sync_status === "SYNCED" ? <Check className="mr-1 inline h-3 w-3" /> : record.sync_status === "FAILED" ? <AlertCircle className="mr-1 inline h-3 w-3" /> : <Clock3 className="mr-1 inline h-3 w-3" />}{sync.text}</span>{record.sheet_row && <span className="text-xs text-muted-foreground">Fila {record.sheet_row}</span>}</div>
                  <p className="mt-2 text-sm text-muted-foreground">Caudal: {numberText(record.discharge_flow_m3)} m³ · pH PLC: {numberText(record.ph_plc)} · pH descarga: {numberText(record.ph_discharge)} · Temp.: {numberText(record.discharge_temp_c)} °C</p>
                </div>
                {canManageWater && <div className="flex gap-2"><Button variant="outline" size="sm" onClick={() => editRecord(record)}>Editar</Button>{record.sync_status === "FAILED" && <Button variant="outline" size="sm" onClick={() => retrySync(record.id)}><RefreshCw className="mr-1 h-3.5 w-3.5" /> Reintentar</Button>}</div>}
              </div>
              {record.meter_readings.length > 0 && <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{record.meter_readings.map((reading) => <div key={reading.meter_key} className="rounded-md bg-muted/40 px-3 py-2 text-sm"><span className="font-medium">{data.meters.find((meter) => meter.key === reading.meter_key)?.label}</span><p className="text-muted-foreground">{numberText(reading.initial_reading)} → {numberText(reading.final_reading)}</p></div>)}</div>}
              {(record.dqo_samples?.length ?? 0) > 0 && <div className="mt-3 space-y-1 text-sm"><p className="font-medium">Análisis DQO</p>{record.dqo_samples.map((sample, index) => <p key={sample.id ?? index} className="text-muted-foreground">Muestra {index + 1}: {fmtDate(sample.date)} · {sample.time || "sin hora"} · Piscina {sample.pool || "—"} · {numberText(sample.mg_l)} mg/L</p>)}</div>}
              {!record.dqo_samples?.length && record.dqo_mg_l !== null && <p className="mt-3 text-sm"><span className="font-medium">DQO:</span> {fmtDate(record.dqo_date ?? "")} · {record.dqo_time} · {record.dqo_pool} · {numberText(record.dqo_mg_l)} mg/L</p>}
              {record.sync_error && <p className="mt-3 rounded-md bg-red-50 p-2 text-xs text-red-700">{record.sync_error}</p>}
              {record.meter_readings.length > 0 && <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4"><p className="col-span-full text-sm font-medium">Volúmenes calculados</p>{record.meter_readings.map((reading) => <p key={`volume-${reading.meter_key}`} className="rounded-md bg-sky-50 px-3 py-2 text-sm text-sky-800"><span className="font-medium">{data.meters.find((meter) => meter.key === reading.meter_key)?.label}:</span> {numberText(reading.volume_m3)} m³</p>)}</div>}
            </Card>;
          })}
        </div>}
      </section>
    </Shell>
  );
}
