"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import * as XLSX from "xlsx";
import { CalendarClock, CheckCircle2, ChevronDown, ClipboardList, FileSpreadsheet, Loader2, Pencil, Plus, RefreshCw, Search, Upload, Wrench, X } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { PageLoading } from "@/components/ui/page-loading";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Worker = { id: number; full_name: string };
type InventoryEquipment = { id: number; name: string; inventory_code: string | null; area_name: string | null; plant_area_name: string | null };
type EquipmentOption = { id: number; name: string; inventory_code: string | null; area_name: string; section_name: string };
type ImportItem = {
  source_plan_id: string | null;
  equipment_inventory_id: string;
  area_name: string | null;
  section_name: string | null;
  equipment_name: string | null;
  periodicity: string | null;
  planned_month: string | null;
  last_completed_date: string | null;
  next_due_date: string | null;
  description: string | null;
  spare_parts: string | null;
  estimated_time: string | null;
  condition: string | null;
  observations: string | null;
};
type ImportMatch = {
  source_plan_id: string | null;
  equipment_inventory_id: string;
  equipment_id: number | null;
  equipment_display_name: string | null;
  status: string;
  reason: string | null;
};
type ImportPreview = { total_with_id: number; matched: number; unmatched: ImportMatch[]; existing: number };
type ImportResult = { imported: number; already_imported: number; unmatched: ImportMatch[] };
type WorkOrderSummary = { id: number; ot_number: string; status: string; created_at: string; completed_at: string | null };
type PreventiveAlertSettings = { alert_days: number; updated_at: string | null };
type Plan = {
  id: number;
  equipment_id: number;
  equipment_name: string;
  inventory_code: string | null;
  area_name: string | null;
  section_name: string | null;
  plant_area: string | null;
  source_plan_id: string | null;
  periodicity: string | null;
  interval_months: number | null;
  planned_month: string | null;
  last_completed_date: string | null;
  next_due_date: string | null;
  description: string | null;
  spare_parts: string | null;
  estimated_time: string | null;
  condition: string | null;
  observations: string | null;
  responsible_name_hint: string | null;
  default_responsible_user_id: number | null;
  default_responsible_name: string | null;
  active: boolean;
  status: string;
  latest_work_order: WorkOrderSummary | null;
};
type PlanDraft = {
  equipment_id: string;
  periodicity: string;
  interval_months: string;
  last_completed_date: string;
  next_due_date: string;
  description: string;
  spare_parts: string;
  estimated_time: string;
  observations: string;
  default_responsible_user_id: string;
};

const PERIODS = [
  ["MONTHLY", "Mensual"],
  ["QUARTERLY", "Trimestral"],
  ["SEMIANNUAL", "Semestral"],
  ["ANNUAL", "Anual"],
  ["CUSTOM", "Personalizada"],
] as const;

const emptyDraft: PlanDraft = {
  equipment_id: "", periodicity: "", interval_months: "", last_completed_date: "", next_due_date: "",
  description: "", spare_parts: "", estimated_time: "", observations: "", default_responsible_user_id: "",
};

function normalizedHeader(value: unknown) {
  return String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function text(value: unknown): string | null {
  const result = String(value ?? "").trim();
  return result || null;
}

function inventoryId(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) return String(Math.trunc(value));
  const result = String(value ?? "").trim();
  return /^\d+\.0+$/.test(result) ? result.replace(/\.0+$/, "") : result;
}

function excelDate(value: unknown): string | null {
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  }
  if (typeof value === "number" && value > 0) {
    const parsed = XLSX.SSF.parse_date_code(value);
    if (parsed) return `${parsed.y}-${String(parsed.m).padStart(2, "0")}-${String(parsed.d).padStart(2, "0")}`;
  }
  const raw = text(value);
  if (!raw) return null;
  const iso = raw.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (iso) return `${iso[1]}-${iso[2].padStart(2, "0")}-${iso[3].padStart(2, "0")}`;
  const local = raw.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{4})/);
  if (local) return `${local[3]}-${local[2].padStart(2, "0")}-${local[1].padStart(2, "0")}`;
  return null;
}

function normalizePeriod(value: unknown): string | null {
  const period = normalizedHeader(value);
  if (period === "mensual") return "MONTHLY";
  if (period === "trimestral") return "QUARTERLY";
  if (period === "semestral") return "SEMIANNUAL";
  if (period === "anual") return "ANNUAL";
  return null;
}

async function parseTemplate(file: File): Promise<{ items: ImportItem[]; skippedNoId: number }> {
  const workbook = XLSX.read(await file.arrayBuffer(), { type: "array", cellDates: true });
  const sheetName = workbook.SheetNames.find((name) => normalizedHeader(name) === "preventivo") || workbook.SheetNames[0];
  if (!sheetName) throw new Error("El archivo no contiene hojas.");
  const rows = XLSX.utils.sheet_to_json<unknown[]>(workbook.Sheets[sheetName], { header: 1, defval: "", raw: true });
  const headerRow = rows.findIndex((row) => {
    const headers = row.map(normalizedHeader);
    return headers.includes("id inv") && headers.includes("equipo") && headers.includes("periodicidad");
  });
  if (headerRow < 0) throw new Error("No encontré la hoja con los encabezados de la plantilla de preventivo.");
  const headers = rows[headerRow].map(normalizedHeader);
  const column = (name: string) => headers.indexOf(name);
  const get = (row: unknown[], name: string) => {
    const index = column(name);
    return index < 0 ? null : row[index];
  };
  const items: ImportItem[] = [];
  let skippedNoId = 0;
  for (let index = headerRow + 1; index < rows.length; index += 1) {
    const row = rows[index];
    if (!row?.some((value) => text(value))) continue;
    const code = inventoryId(get(row, "id inv"));
    if (!code) { skippedNoId += 1; continue; }
    items.push({
      source_plan_id: text(get(row, "id prev")),
      equipment_inventory_id: code,
      area_name: text(get(row, "area")),
      section_name: text(get(row, "seccion")),
      equipment_name: text(get(row, "equipo")),
      periodicity: normalizePeriod(get(row, "periodicidad")),
      planned_month: text(get(row, "mes programado")) || text(get(row, "mes")),
      last_completed_date: excelDate(get(row, "fecha efectuada")),
      next_due_date: excelDate(get(row, "proxima fecha")),
      description: text(get(row, "trabajo asignado")),
      spare_parts: text(get(row, "repuestos")),
      estimated_time: text(get(row, "horas")),
      condition: text(get(row, "condicion")),
      observations: text(get(row, "observaciones")),
    });
  }
  return { items, skippedNoId };
}

function dateLabel(value: string | null) {
  if (!value) return "Sin fecha";
  const [year, month, day] = value.slice(0, 10).split("-");
  return `${day}-${month}-${year}`;
}

function calculateNextDueDate(baseDate: string, periodicity: string, intervalMonths: string): string {
  if (!baseDate || !periodicity) return "";
  const fixedIntervals: Record<string, number> = { MONTHLY: 1, QUARTERLY: 3, SEMIANNUAL: 6, ANNUAL: 12 };
  const months = periodicity === "CUSTOM" ? Number(intervalMonths) : fixedIntervals[periodicity];
  if (!Number.isInteger(months) || months < 1 || months > 120) return "";
  const [year, month, day] = baseDate.split("-").map(Number);
  if (!year || !month || !day) return "";
  const monthIndex = year * 12 + month - 1 + months;
  const nextYear = Math.floor(monthIndex / 12);
  const nextMonthIndex = monthIndex % 12;
  const nextMonth = nextMonthIndex + 1;
  const lastDay = new Date(Date.UTC(nextYear, nextMonth, 0)).getUTCDate();
  const nextDay = Math.min(day, lastDay);
  return `${nextYear}-${String(nextMonth).padStart(2, "0")}-${String(nextDay).padStart(2, "0")}`;
}

const statusLabels: Record<string, string> = {
  ON_TIME: "Al día", DUE_SOON: "Próximo", OVERDUE: "Vencido", NEEDS_CONFIGURATION: "Falta configurar",
  OT_OPEN: "OT abierta", INACTIVE: "Inactivo",
};
const statusClasses: Record<string, string> = {
  ON_TIME: "bg-emerald-100 text-emerald-800", DUE_SOON: "bg-amber-100 text-amber-800",
  OVERDUE: "bg-red-100 text-red-800", NEEDS_CONFIGURATION: "bg-slate-100 text-slate-700",
  OT_OPEN: "bg-blue-100 text-blue-800", INACTIVE: "bg-slate-100 text-slate-500",
};

export default function PreventivoPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [equipment, setEquipment] = useState<EquipmentOption[]>([]);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [alertDays, setAlertDays] = useState(30);
  const [alertDaysDraft, setAlertDaysDraft] = useState("30");
  const [savingAlertDays, setSavingAlertDays] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [draft, setDraft] = useState<PlanDraft>(emptyDraft);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [createPlanOpen, setCreatePlanOpen] = useState(false);
  const [importItems, setImportItems] = useState<ImportItem[]>([]);
  const [skippedNoId, setSkippedNoId] = useState(0);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [responsibleByPlan, setResponsibleByPlan] = useState<Record<number, string>>({});
  const [historyByPlan, setHistoryByPlan] = useState<Record<number, WorkOrderSummary[]>>({});
  const [historyOpen, setHistoryOpen] = useState<number | null>(null);
  const topHorizontalScrollRef = useRef<HTMLDivElement | null>(null);
  const tableHorizontalScrollRef = useRef<HTMLDivElement | null>(null);
  const planListRef = useRef<HTMLElement | null>(null);
  const deepLinkHandledRef = useRef(false);
  const statusDeepLinkHandledRef = useRef(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const [plansData, inventory, workersData, alertSettings] = await Promise.all([
        api.get<Plan[]>("/api/preventive/plans?include_inactive=true"),
        api.get<InventoryEquipment[]>("/api/catalogs/equipment-inventory"),
        api.get<Worker[]>("/api/users/workers"),
        api.get<PreventiveAlertSettings>("/api/preventive/settings"),
      ]);
      const equipmentData = inventory.map((item) => ({
        id: item.id, name: item.name, inventory_code: item.inventory_code || null,
        area_name: item.plant_area_name || "Área general sin asignar",
        section_name: item.area_name || "Sección sin asignar",
      }));
      setPlans(plansData);
      setEquipment(equipmentData);
      setWorkers(workersData);
      setAlertDays(alertSettings.alert_days);
      setAlertDaysDraft(String(alertSettings.alert_days));
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cargar el módulo preventivo.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
    else if (!loading && user && user.role !== "ADMIN") router.replace("/dashboard");
  }, [loading, user, router]);

  useEffect(() => { if (user?.role === "ADMIN") void load(); }, [user, load]);

  async function saveAlertDays() {
    const value = Number(alertDaysDraft);
    if (!Number.isInteger(value) || value < 1 || value > 365) {
      setError("El plazo de anticipación debe estar entre 1 y 365 días.");
      return;
    }
    setError(""); setNotice(""); setSavingAlertDays(true);
    try {
      const saved = await api.patch<PreventiveAlertSettings>("/api/preventive/settings", { alert_days: value });
      setAlertDays(saved.alert_days);
      setAlertDaysDraft(String(saved.alert_days));
      setNotice(`La anticipación de alertas quedó configurada en ${saved.alert_days} días.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar la anticipación de alertas.");
    } finally {
      setSavingAlertDays(false);
    }
  }

  const filteredPlans = useMemo(() => {
    const query = normalizedHeader(search);
    return plans.filter((plan) => {
      if (statusFilter !== "ALL" && plan.status !== statusFilter) return false;
      const source = normalizedHeader([plan.equipment_name, plan.inventory_code, plan.area_name, plan.section_name, plan.description, plan.source_plan_id].join(" "));
      return !query || source.includes(query);
    });
  }, [plans, search, statusFilter]);

  useEffect(() => {
    if (deepLinkHandledRef.current || plans.length === 0) return;
    const planId = Number(new URLSearchParams(window.location.search).get("plan_id"));
    if (!planId || !plans.some((plan) => plan.id === planId)) return;
    deepLinkHandledRef.current = true;
    setSearch("");
    setStatusFilter("ALL");
    requestAnimationFrame(() => document.getElementById(`preventive-plan-${planId}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }, [plans]);

  useEffect(() => {
    if (statusDeepLinkHandledRef.current || plans.length === 0) return;
    const requestedStatus = new URLSearchParams(window.location.search).get("status");
    if (requestedStatus !== "OVERDUE" && requestedStatus !== "DUE_SOON") return;
    statusDeepLinkHandledRef.current = true;
    setSearch("");
    setStatusFilter(requestedStatus);
    requestAnimationFrame(() => planListRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }, [plans]);

  const counters = useMemo(() => plans.reduce((acc, plan) => {
    acc[plan.status] = (acc[plan.status] || 0) + 1;
    return acc;
  }, {} as Record<string, number>), [plans]);

  function resetDraft() { setDraft(emptyDraft); setEditingId(null); }

  function beginEdit(plan: Plan) {
    setEditingId(plan.id);
    setCreatePlanOpen(false);
    setDraft({
      equipment_id: String(plan.equipment_id), periodicity: plan.periodicity || "", interval_months: plan.interval_months ? String(plan.interval_months) : "",
      last_completed_date: plan.last_completed_date || "", next_due_date: plan.next_due_date || "", description: plan.description || "",
      spare_parts: plan.spare_parts || "", estimated_time: plan.estimated_time || "", observations: plan.observations || "",
      default_responsible_user_id: plan.default_responsible_user_id ? String(plan.default_responsible_user_id) : "",
    });
  }

  async function savePlan(event: React.FormEvent) {
    event.preventDefault();
    setError(""); setNotice("");
    if (!draft.equipment_id || !draft.periodicity || !draft.next_due_date || !draft.description.trim()) {
      setError("Para guardar, selecciona equipo, periodicidad, próxima fecha y descripción."); return;
    }
    if (draft.periodicity === "CUSTOM" && !draft.interval_months) {
      setError("Indica cada cuántos meses se repetirá este preventivo."); return;
    }
    setBusy(true);
    const payload = {
      equipment_id: Number(draft.equipment_id), periodicity: draft.periodicity,
      interval_months: draft.interval_months ? Number(draft.interval_months) : null,
      last_completed_date: draft.last_completed_date || null, next_due_date: draft.next_due_date || null,
      description: draft.description.trim(), spare_parts: draft.spare_parts || null, estimated_time: draft.estimated_time || null,
      observations: draft.observations || null,
      default_responsible_user_id: draft.default_responsible_user_id ? Number(draft.default_responsible_user_id) : null,
    };
    try {
      if (editingId) {
        await api.patch(`/api/preventive/plans/${editingId}`, payload);
        setNotice("Plan preventivo actualizado.");
      } else {
        await api.post("/api/preventive/plans", payload);
        setNotice("Plan preventivo creado.");
        setCreatePlanOpen(false);
      }
      resetDraft();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar el plan.");
    } finally { setBusy(false); }
  }

  async function toggleActive(plan: Plan) {
    setError(""); setNotice(""); setBusy(true);
    try {
      await api.patch(`/api/preventive/plans/${plan.id}`, { active: !plan.active });
      setNotice(plan.active ? "Plan preventivo desactivado." : "Plan preventivo activado.");
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : "No se pudo actualizar el estado."); }
    finally { setBusy(false); }
  }

  async function chooseImport(file: File) {
    setError(""); setNotice(""); setPreview(null); setImportResult(null); setBusy(true);
    try {
      const parsed = await parseTemplate(file);
      if (!parsed.items.length) throw new Error("No hay filas con ID de equipo. No se importó ningún registro.");
      const result = await api.post<ImportPreview>("/api/preventive/import/preview", { items: parsed.items });
      setImportItems(parsed.items); setSkippedNoId(parsed.skippedNoId); setPreview(result);
      setNotice("Revisa las coincidencias antes de importar. Las filas sin ID fueron descartadas.");
    } catch (err) { setError(err instanceof Error ? err.message : "No se pudo leer la planilla."); }
    finally { setBusy(false); }
  }

  async function confirmImport() {
    setError(""); setNotice(""); setBusy(true);
    try {
      const result = await api.post<ImportResult>("/api/preventive/import", { items: importItems });
      setImportResult(result);
      setNotice(`Importación local terminada: ${result.imported} planes agregados; ${result.already_imported} ya estaban importados; ${result.unmatched.length} requieren revisión.`);
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : "No se pudo importar la plantilla."); }
    finally { setBusy(false); }
  }

  async function generateOT(plan: Plan) {
    setError(""); setNotice("");
    const responsibleId = responsibleByPlan[plan.id] || (plan.default_responsible_user_id ? String(plan.default_responsible_user_id) : "");
    if (!responsibleId) { setError(`Selecciona responsable para ${plan.equipment_name} antes de generar la OT.`); return; }
    setBusy(true);
    try {
      const result = await api.post<{ id: number; ot_number: string }>(`/api/preventive/plans/${plan.id}/generate-ot`, { responsible_user_id: Number(responsibleId) });
      setNotice(`Se generó la OT ${result.ot_number} para ${plan.equipment_name}.`);
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : "No se pudo generar la OT preventiva."); }
    finally { setBusy(false); }
  }

  async function toggleHistory(planId: number) {
    if (historyOpen === planId) { setHistoryOpen(null); return; }
    setHistoryOpen(planId);
    if (historyByPlan[planId]) return;
    try {
      const history = await api.get<WorkOrderSummary[]>(`/api/preventive/plans/${planId}/work-orders`);
      setHistoryByPlan((current) => ({ ...current, [planId]: history }));
    } catch (err) { setError(err instanceof Error ? err.message : "No se pudo cargar el historial de OTs."); }
  }

  if (loading || !user || user.role !== "ADMIN") return <PageLoading />;

  const equipmentOptions = equipment.map((item) => ({
    value: String(item.id),
    label: `${item.name}${item.inventory_code ? ` — ID ${item.inventory_code}` : ""} · ${item.area_name} → ${item.section_name}`,
  }));

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      <div className="space-y-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <span className="rounded-xl bg-indigo-100 p-3 text-indigo-700"><CalendarClock className="h-6 w-6" /></span>
              <div><h1 className="text-2xl font-bold">Mantenimiento preventivo</h1><p className="text-sm text-muted-foreground">Planes, vencimientos y OTs preventivas por equipo.</p></div>
            </div>
          </div>
          <Button variant="outline" onClick={() => void load()} disabled={busy}><RefreshCw className={`mr-2 h-4 w-4 ${busy ? "animate-spin" : ""}`} />Actualizar</Button>
        </div>

        {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>}
        {notice && <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</div>}

        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {[["Al día", counters.ON_TIME || 0, "text-emerald-700"], ["Próximos", counters.DUE_SOON || 0, "text-amber-700"], ["Vencidos", counters.OVERDUE || 0, "text-red-700"], ["OT abierta", counters.OT_OPEN || 0, "text-blue-700"], ["Falta configurar", counters.NEEDS_CONFIGURATION || 0, "text-slate-700"]].map(([label, value, color]) => (
            <button key={String(label)} type="button" onClick={() => { setStatusFilter(label === "Al día" ? "ON_TIME" : label === "Próximos" ? "DUE_SOON" : label === "Vencidos" ? "OVERDUE" : label === "OT abierta" ? "OT_OPEN" : "NEEDS_CONFIGURATION"); requestAnimationFrame(() => planListRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })); }} className="rounded-lg border bg-card p-4 text-left shadow-sm hover:border-primary/40">
              <div className="text-sm text-muted-foreground">{label}</div><div className={`mt-1 text-2xl font-bold ${color}`}>{value}</div>
            </button>
          ))}
        </section>

        <section className="flex flex-wrap items-end gap-4 rounded-xl border bg-card p-4 shadow-sm">
          <div className="mr-auto min-w-56">
            <h2 className="font-semibold">Anticipación de alertas</h2>
            <p className="mt-1 text-sm text-muted-foreground">Avisar a los administradores antes del vencimiento. Los vencidos se alertan al pasar la fecha.</p>
          </div>
          <label className="text-sm font-medium">Avisar con cuántos días<input className="mt-1 h-10 w-36 rounded-md border bg-background px-3" type="number" min="1" max="365" value={alertDaysDraft} onChange={(event) => setAlertDaysDraft(event.target.value)} /></label>
          <span className="pb-2 text-sm text-muted-foreground">días (actual: {alertDays})</span>
          <Button type="button" onClick={() => void saveAlertDays()} disabled={savingAlertDays || busy}>{savingAlertDays ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}Guardar plazo</Button>
        </section>

        <section className="rounded-xl border bg-card p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-2"><FileSpreadsheet className="h-5 w-5 text-primary" /><h2 className="text-lg font-semibold">Cargar planilla de preventivos</h2></div>
          <p className="mb-4 text-sm text-muted-foreground">Se importan solamente filas que tengan ID de inventario. Antes de guardar, la app compara cada ID con el inventario local; no crea equipos por sí sola.</p>
          <label className="inline-flex cursor-pointer items-center rounded-md border px-3 py-2 text-sm font-medium hover:bg-muted">
            {busy && !preview ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}Elegir Excel
            <input type="file" accept=".xlsx,.xls" className="sr-only" disabled={busy} onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void chooseImport(file); }} />
          </label>
          {preview && <div className="mt-4 space-y-3 rounded-lg bg-muted/40 p-4">
            <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm"><span>Con ID: <b>{preview.total_with_id}</b></span><span>Coincidencias: <b>{preview.matched}</b></span><span>Ya importadas: <b>{preview.existing}</b></span><span>Sin ID omitidas: <b>{skippedNoId}</b></span><span>Sin frecuencia: <b>{importItems.filter((item) => !item.periodicity).length}</b></span><span>Sin próxima fecha: <b>{importItems.filter((item) => !item.next_due_date).length}</b></span></div>
            {preview.unmatched.length > 0 && <div className="max-h-48 overflow-auto rounded border bg-background p-3 text-sm"><b>Revisar antes de importar ({preview.unmatched.length})</b><ul className="mt-2 list-disc space-y-1 pl-5">{preview.unmatched.slice(0, 30).map((item, index) => <li key={`${item.equipment_inventory_id}-${index}`}>ID {item.equipment_inventory_id}{item.equipment_display_name ? ` · ${item.equipment_display_name}` : ""}: {item.reason || item.status}</li>)}</ul>{preview.unmatched.length > 30 && <p className="mt-2 text-muted-foreground">Se muestran 30; el resultado completo aparecerá después de importar.</p>}</div>}
            <div className="flex flex-wrap gap-2"><Button onClick={() => void confirmImport()} disabled={busy || preview.matched <= preview.existing}><CheckCircle2 className="mr-2 h-4 w-4" />Importar coincidencias nuevas</Button><Button variant="outline" onClick={() => { setPreview(null); setImportItems([]); setImportResult(null); }}>Cancelar</Button></div>
            {importResult?.unmatched.length ? <p className="text-sm text-amber-800">{importResult.unmatched.length} fila(s) no se guardaron por falta de coincidencia exacta.</p> : null}
          </div>}
        </section>

        <section className={editingId ? "fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-slate-950/50 p-3 sm:p-6" : "rounded-xl border bg-card p-5 shadow-sm"} role={editingId ? "dialog" : undefined} aria-modal={editingId ? true : undefined} aria-labelledby={editingId ? "preventive-form-title" : undefined} onMouseDown={(event) => { if (editingId && event.target === event.currentTarget) resetDraft(); }}>
          <div className={editingId ? "my-auto max-h-[94vh] w-full max-w-5xl overflow-y-auto rounded-xl border bg-card p-5 shadow-2xl sm:p-6" : ""}>
          {editingId ? <div className="mb-4 flex items-center gap-2"><Plus className="h-5 w-5 text-primary" /><h2 id="preventive-form-title" className="mr-auto text-lg font-semibold">Editar plan preventivo</h2><Button type="button" variant="outline" size="sm" onClick={resetDraft} aria-label="Cerrar edición"><X className="h-4 w-4" /></Button></div> : <button type="button" aria-expanded={createPlanOpen} onClick={() => setCreatePlanOpen((open) => !open)} className="flex w-full items-center gap-3 text-left"><Plus className="h-5 w-5 text-primary" /><span className="mr-auto text-lg font-semibold">Agregar equipo al plan</span><ChevronDown className={`h-5 w-5 text-muted-foreground transition-transform ${createPlanOpen ? "rotate-180" : ""}`} /></button>}
          {(editingId || createPlanOpen) && <div className="pt-4">
          <form onSubmit={(event) => void savePlan(event)} className="space-y-4">
            <SearchableSelect label="Equipo del inventario" options={equipmentOptions} value={draft.equipment_id} onValueChange={(value) => setDraft((current) => ({ ...current, equipment_id: value }))} placeholder="Buscar equipo por nombre, ID, área o sección..." searchPlaceholder="Escribe nombre o código..." emptyMessage="No se encontraron equipos en el inventario." disabled={!!editingId} />
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label className="text-sm font-medium">Periodicidad<select className="mt-1 h-10 w-full rounded-md border bg-background px-3" value={draft.periodicity} onChange={(event) => setDraft((current) => { const periodicity = event.target.value; const intervalMonths = periodicity === "CUSTOM" ? current.interval_months : ""; const calculated = calculateNextDueDate(current.last_completed_date, periodicity, intervalMonths); return { ...current, periodicity, interval_months: intervalMonths, next_due_date: calculated || (periodicity ? "" : current.next_due_date) }; })}><option value="">Seleccionar...</option>{PERIODS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              {draft.periodicity === "CUSTOM" && <label className="text-sm font-medium">Cada cuántos meses<input className="mt-1 h-10 w-full rounded-md border bg-background px-3" type="number" min="1" max="120" value={draft.interval_months} onChange={(event) => setDraft((current) => { const intervalMonths = event.target.value; const calculated = calculateNextDueDate(current.last_completed_date, current.periodicity, intervalMonths); return { ...current, interval_months: intervalMonths, next_due_date: calculated || "" }; })} /></label>}
              <label className="text-sm font-medium">Fecha base / última realizada<input className="mt-1 h-10 w-full rounded-md border bg-background px-3" type="date" value={draft.last_completed_date} onChange={(event) => setDraft((current) => { const lastCompletedDate = event.target.value; const calculated = calculateNextDueDate(lastCompletedDate, current.periodicity, current.interval_months); return { ...current, last_completed_date: lastCompletedDate, next_due_date: calculated || current.next_due_date }; })} /></label>
              <label className="text-sm font-medium">Próximo vencimiento<input className="mt-1 h-10 w-full rounded-md border bg-background px-3" type="date" required value={draft.next_due_date} onChange={(event) => setDraft((current) => ({ ...current, next_due_date: event.target.value }))} /><span className="mt-1 block text-xs font-normal text-muted-foreground">Se calcula desde la fecha base y la periodicidad; puedes corregirla si es necesario.</span></label>
              <label className="text-sm font-medium">Responsable sugerido<select className="mt-1 h-10 w-full rounded-md border bg-background px-3" value={draft.default_responsible_user_id} onChange={(event) => setDraft((current) => ({ ...current, default_responsible_user_id: event.target.value }))}><option value="">Elegir al generar la OT</option>{workers.map((worker) => <option key={worker.id} value={worker.id}>{worker.full_name}</option>)}</select></label>
              <label className="text-sm font-medium">Horas estimadas<input className="mt-1 h-10 w-full rounded-md border bg-background px-3" value={draft.estimated_time} onChange={(event) => setDraft((current) => ({ ...current, estimated_time: event.target.value }))} placeholder="Ej. 2 horas" /></label>
            </div>
            <label className="block text-sm font-medium">Trabajo asignado / descripción<textarea required className="mt-1 min-h-24 w-full rounded-md border bg-background px-3 py-2" value={draft.description} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} placeholder="Inspecciones y tareas que debe incluir la OT..." /></label>
            <div className="grid gap-3 md:grid-cols-2"><label className="text-sm font-medium">Repuestos<textarea className="mt-1 min-h-16 w-full rounded-md border bg-background px-3 py-2" value={draft.spare_parts} onChange={(event) => setDraft((current) => ({ ...current, spare_parts: event.target.value }))} /></label><label className="text-sm font-medium">Observaciones<textarea className="mt-1 min-h-16 w-full rounded-md border bg-background px-3 py-2" value={draft.observations} onChange={(event) => setDraft((current) => ({ ...current, observations: event.target.value }))} /></label></div>
            <div className="flex gap-2"><Button type="submit" disabled={busy}>{busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Wrench className="mr-2 h-4 w-4" />}{editingId ? "Guardar cambios" : "Crear plan"}</Button>{editingId && <Button type="button" variant="outline" onClick={resetDraft}><X className="mr-1 h-4 w-4" />Cancelar edición</Button>}</div>
          </form>
          </div>}
          </div>
        </section>

        <section ref={planListRef} className="scroll-mt-20 space-y-3">
          <div className="flex flex-wrap items-center gap-3"><h2 className="mr-auto text-lg font-semibold">Equipos con preventivo ({filteredPlans.length})</h2><div className="relative w-full sm:w-80"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input className="pl-9" placeholder="Buscar equipo, ID, área o tarea" value={search} onChange={(event) => setSearch(event.target.value)} /></div><select className="h-10 rounded-md border bg-background px-3 text-sm" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="ALL">Todos los estados</option><option value="ON_TIME">Al día</option><option value="DUE_SOON">Próximos</option><option value="OVERDUE">Vencidos</option><option value="OT_OPEN">OT abierta</option><option value="NEEDS_CONFIGURATION">Falta configurar</option><option value="INACTIVE">Inactivos</option></select></div>
          {filteredPlans.length === 0 ? <div className="rounded-xl border bg-card p-10 text-center text-muted-foreground">{busy ? "Cargando planes..." : "No hay planes que coincidan con la búsqueda."}</div> : <>
            <div ref={topHorizontalScrollRef} className="sticky top-14 z-20 h-5 overflow-x-auto overflow-y-hidden rounded-t-xl border border-b-0 bg-muted/70" aria-label="Desplazar tabla de preventivos horizontalmente" onScroll={(event) => { if (tableHorizontalScrollRef.current && tableHorizontalScrollRef.current.scrollLeft !== event.currentTarget.scrollLeft) tableHorizontalScrollRef.current.scrollLeft = event.currentTarget.scrollLeft; }}>
              <div className="h-1 min-w-[1450px]" />
            </div>
            <div ref={tableHorizontalScrollRef} className="overflow-x-auto rounded-b-xl border bg-card shadow-sm" onScroll={(event) => { if (topHorizontalScrollRef.current && topHorizontalScrollRef.current.scrollLeft !== event.currentTarget.scrollLeft) topHorizontalScrollRef.current.scrollLeft = event.currentTarget.scrollLeft; }}>
            <table className="w-full min-w-[1450px] border-collapse text-left text-xs">
              <thead className="bg-muted/70 text-muted-foreground"><tr>
                <th className="whitespace-nowrap px-3 py-2.5 font-semibold">Equipo / ID</th>
                <th className="px-3 py-2.5 font-semibold">Área / sección</th>
                <th className="whitespace-nowrap px-3 py-2.5 font-semibold">Frecuencia</th>
                <th className="whitespace-nowrap px-3 py-2.5 font-semibold">Última / próxima</th>
                <th className="min-w-64 px-3 py-2.5 font-semibold">Trabajo / repuestos</th>
                <th className="min-w-48 px-3 py-2.5 font-semibold">Responsable</th>
                <th className="min-w-64 px-3 py-2.5 font-semibold">Estado / acciones</th>
              </tr></thead>
              {filteredPlans.map((plan) => {
                const responsibleValue = responsibleByPlan[plan.id] || (plan.default_responsible_user_id ? String(plan.default_responsible_user_id) : "");
                const hasOpenOT = plan.status === "OT_OPEN";
                return <tbody key={plan.id} id={`preventive-plan-${plan.id}`} className="divide-y border-t">
                  <tr className="align-top hover:bg-muted/20">
                    <td className="max-w-56 px-3 py-2.5"><div className="font-semibold text-foreground" title={plan.equipment_name}>{plan.equipment_name}</div><div className="mt-0.5 text-muted-foreground">{plan.inventory_code ? `ID ${plan.inventory_code}` : "Sin ID"}</div></td>
                    <td className="max-w-48 px-3 py-2.5"><div title={plan.area_name || "Área sin vincular"}>{plan.area_name || "Área sin vincular"}</div><div className="mt-0.5 text-muted-foreground" title={plan.section_name || "Sin sección"}>{plan.section_name || "Sin sección"}</div></td>
                    <td className="whitespace-nowrap px-3 py-2.5">{PERIODS.find(([value]) => value === plan.periodicity)?.[1] || "Sin configurar"}{plan.periodicity === "CUSTOM" && plan.interval_months ? <div className="mt-0.5 text-muted-foreground">Cada {plan.interval_months} meses</div> : null}</td>
                    <td className="whitespace-nowrap px-3 py-2.5"><div><span className="text-muted-foreground">Última:</span> {dateLabel(plan.last_completed_date)}</div><div className="mt-0.5"><span className="text-muted-foreground">Próxima:</span> {dateLabel(plan.next_due_date)}</div>{plan.latest_work_order && <div className="mt-1"><a className="text-primary underline" href={`/ordenes/${plan.latest_work_order.id}`}>{plan.latest_work_order.ot_number}</a></div>}</td>
                    <td className="max-w-[360px] px-3 py-2.5"><div className="line-clamp-2 whitespace-pre-wrap" title={plan.description || "Falta agregar descripción."}>{plan.description || <span className="text-amber-700">Falta descripción.</span>}</div>{plan.spare_parts && <div className="mt-1 line-clamp-1 text-muted-foreground" title={`Repuestos: ${plan.spare_parts}`}><span className="font-medium">Repuestos:</span> {plan.spare_parts}</div>}</td>
                    <td className="min-w-48 px-3 py-2.5"><div className="mb-1 truncate" title={plan.default_responsible_name || "Sin asignar"}>{plan.default_responsible_name || "Sin asignar"}</div>{plan.active ? <select aria-label={`Responsable para OT de ${plan.equipment_name}`} className="h-8 w-full rounded-md border bg-background px-2 text-xs" value={responsibleValue} onChange={(event) => setResponsibleByPlan((current) => ({ ...current, [plan.id]: event.target.value }))}><option value="">Elegir trabajador...</option>{workers.map((worker) => <option key={worker.id} value={worker.id}>{worker.full_name}</option>)}</select> : <span className="text-muted-foreground">Plan inactivo</span>}</td>
                    <td className="px-3 py-2.5"><div><span className={`rounded-full px-2 py-0.5 font-semibold ${statusClasses[plan.status] || "bg-muted"}`}>{statusLabels[plan.status] || plan.status}</span></div><div className="mt-2 flex flex-wrap gap-1.5"><Button type="button" variant="outline" size="sm" className="h-8 px-2 text-xs" onClick={() => beginEdit(plan)}><Pencil className="mr-1 h-3.5 w-3.5" />Editar</Button><Button type="button" variant="outline" size="sm" className="h-8 px-2 text-xs" onClick={() => void toggleActive(plan)} disabled={busy}>{plan.active ? "Desactivar" : "Activar"}</Button>{plan.active && <Button type="button" size="sm" className="h-8 px-2 text-xs" onClick={() => void generateOT(plan)} disabled={busy || hasOpenOT || plan.status === "NEEDS_CONFIGURATION"}><ClipboardList className="mr-1 h-3.5 w-3.5" />{hasOpenOT ? "OT abierta" : "Generar OT"}</Button>}</div><button type="button" className="mt-1 text-xs font-medium text-primary hover:underline" onClick={() => void toggleHistory(plan.id)}>{historyOpen === plan.id ? "Ocultar historial" : "Historial de OTs"}</button>{plan.latest_work_order && <div className="mt-1 text-[11px] text-muted-foreground">{plan.latest_work_order.status === "COMPLETED" || plan.latest_work_order.status === "APPROVED" ? `Finalizada ${dateLabel(plan.latest_work_order.completed_at)}` : `Última OT: ${plan.latest_work_order.status}`}</div>}</td>
                  </tr>
                  {historyOpen === plan.id && <tr><td colSpan={7} className="bg-muted/30 px-4 py-2.5"><div className="flex flex-wrap gap-x-5 gap-y-1 text-xs">{historyByPlan[plan.id]?.length ? historyByPlan[plan.id].map((order) => <span key={order.id}><a className="text-primary underline" href={`/ordenes/${order.id}`}>{order.ot_number}</a> · {order.status} · creada {dateLabel(order.created_at)}</span>) : <span className="text-muted-foreground">Aún no hay OTs asociadas.</span>}</div></td></tr>}
                </tbody>;
              })}
            </table>
            </div>
          </>}
        </section>
      </div>
    </Shell>
  );
}
