"use client";

import { useEffect, useState } from "react";
import * as XLSX from "xlsx";
import { FileSpreadsheet, Loader2, Search, SlidersHorizontal, Upload, X } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { formatDateOnly } from "@/lib/utils";

type ImportItem = {
  source_row: number;
  original_ot_number: string | null;
  source_responsible: string | null;
  title: string;
  description: string;
  execution_date: string;
  duration_minutes: number;
  duration_text: string;
};

type PendingItem = {
  id: number;
  ot_number: string;
  original_ot_number: string | null;
  title: string;
  execution_date: string | null;
  responsible_user_name: string | null;
  classification_status: "WITHOUT_AREA" | "WITHOUT_SECTION" | "WITHOUT_EQUIPMENT" | "COMPLETE";
};

type Worker = { id: number; full_name: string };

type ClassificationStatus = "PENDING" | "WITHOUT_AREA" | "WITHOUT_SECTION" | "WITHOUT_EQUIPMENT" | "COMPLETE" | "ALL";

type PendingFilters = {
  search: string;
  dateFrom: string;
  dateTo: string;
  responsibleUserId: string;
  classificationStatus: ClassificationStatus;
  sortDirection: "asc" | "desc";
};

type ImportResult = {
  received: number;
  created: number;
  skipped: number;
  unmatched_responsibles: string[];
};

function text(value: unknown) {
  return String(value ?? "").trim();
}

function headerKey(value: unknown) {
  return text(value)
    .replace(/[�]/g, "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function findColumn(headers: string[], options: string[]) {
  return headers.findIndex((header) =>
    options.some((option) => header === option || header.startsWith(option) || header.includes(option)),
  );
}

function parseDate(value: unknown): string | null {
  const raw = text(value);
  if (!raw) return null;
  const iso = raw.match(/^(\d{4})[-/]([01]\d)[-/]([0-3]\d)/);
  if (iso) return `${iso[1]}-${iso[2]}-${iso[3]}`;
  const dmy = raw.match(/^([0-3]\d)[-/]([01]\d)[-/](\d{4})/);
  if (dmy) return `${dmy[3]}-${dmy[2]}-${dmy[1]}`;
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return null;
  return `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, "0")}-${String(parsed.getDate()).padStart(2, "0")}`;
}

function parseDuration(durationText: string, decimalValue: unknown): number {
  const raw = durationText.toLowerCase().replace(",", ".");
  const hours = Number(raw.match(/(\d+(?:\.\d+)?)\s*h/)?.[1] || 0);
  const minutes = Number(raw.match(/(\d+)\s*m(?:in)?/)?.[1] || 0);
  const parsed = Math.round(hours * 60 + minutes);
  if (parsed > 0) return parsed;
  const decimal = Number(text(decimalValue).replace(",", "."));
  return Number.isFinite(decimal) && decimal > 0 ? Math.round(decimal * 60) : 0;
}

const emptyFilters: PendingFilters = {
  search: "",
  dateFrom: "",
  dateTo: "",
  responsibleUserId: "",
  classificationStatus: "PENDING",
  sortDirection: "asc",
};

const classificationLabels: Record<PendingItem["classification_status"], string> = {
  WITHOUT_AREA: "Sin área",
  WITHOUT_SECTION: "Sin sección",
  WITHOUT_EQUIPMENT: "Sin equipo",
  COMPLETE: "Completa",
};

const classificationClasses: Record<PendingItem["classification_status"], string> = {
  WITHOUT_AREA: "bg-amber-100 text-amber-800",
  WITHOUT_SECTION: "bg-orange-100 text-orange-800",
  WITHOUT_EQUIPMENT: "bg-blue-100 text-blue-800",
  COMPLETE: "bg-emerald-100 text-emerald-800",
};

async function parseWorkbook(file: File): Promise<ImportItem[]> {
  const workbook = XLSX.read(await file.arrayBuffer(), { type: "array", raw: false });
  const sheetName = workbook.SheetNames.find((name) => /ot consolid/i.test(name)) || workbook.SheetNames[0];
  if (!sheetName) throw new Error("La planilla no contiene hojas.");
  const rows = XLSX.utils.sheet_to_json<unknown[]>(workbook.Sheets[sheetName], { header: 1, defval: "", raw: false });
  const headerRow = rows.findIndex((row) => {
    const headers = row.map(headerKey);
    return headers.some((value) => value.includes("equipo intervenido")) && headers.some((value) => value.includes("fecha ejec"));
  });
  if (headerRow < 0) throw new Error("No encontre la hoja con las columnas de OT Consolidadas.");

  const headers = rows[headerRow].map(headerKey);
  const otIndex = findColumn(headers, ["n ot", "n o ot", "numero ot", "ot"]);
  const responsibleIndex = findColumn(headers, ["responsable s", "responsables", "responsable"]);
  const equipmentIndex = findColumn(headers, ["equipo intervenido"]);
  const descriptionIndex = findColumn(headers, ["descripcion del trabajo", "descripci", "descripcion"]);
  const durationIndex = findColumn(headers, ["duracion", "duraci"]);
  const decimalIndex = findColumn(headers, ["horas decimal", "horas decim"]);
  const dateIndex = findColumn(headers, ["fecha ejecucion", "fecha ejec"]);
  if ([equipmentIndex, descriptionIndex, dateIndex].some((index) => index < 0)) {
    throw new Error("Faltan columnas obligatorias: Equipo intervenido, Descripcion del trabajo o Fecha ejecucion.");
  }

  const items: ImportItem[] = [];
  for (let index = headerRow + 1; index < rows.length; index += 1) {
    const row = rows[index];
    if (!row?.some((value) => text(value))) continue;
    const title = text(row[equipmentIndex]);
    const description = text(row[descriptionIndex]);
    const executionDate = parseDate(row[dateIndex]);
    const durationText = durationIndex >= 0 ? text(row[durationIndex]) : "";
    const durationMinutes = parseDuration(durationText, decimalIndex >= 0 ? row[decimalIndex] : "");
    if (!title || !description || !executionDate || durationMinutes <= 0) {
      throw new Error(`La fila ${index + 1} tiene titulo, descripcion, fecha o duracion invalida.`);
    }
    items.push({
      source_row: index + 1,
      original_ot_number: otIndex >= 0 ? text(row[otIndex]) || null : null,
      source_responsible: responsibleIndex >= 0 ? text(row[responsibleIndex]) || null : null,
      title,
      description,
      execution_date: executionDate,
      duration_minutes: durationMinutes,
      duration_text: durationText,
    });
  }
  return items;
}

export function HistoricalWorkOrderImport() {
  const [items, setItems] = useState<ImportItem[]>([]);
  const [pending, setPending] = useState<PendingItem[]>([]);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [filters, setFilters] = useState<PendingFilters>(emptyFilters);
  const [busy, setBusy] = useState(false);
  const [loadingPending, setLoadingPending] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function loadPending(activeFilters: PendingFilters) {
    setLoadingPending(true);
    try {
      const params = new URLSearchParams();
      if (activeFilters.search.trim()) params.set("search", activeFilters.search.trim());
      if (activeFilters.dateFrom) params.set("date_from", activeFilters.dateFrom);
      if (activeFilters.dateTo) params.set("date_to", activeFilters.dateTo);
      if (activeFilters.responsibleUserId) params.set("responsible_user_id", activeFilters.responsibleUserId);
      params.set("classification_status", activeFilters.classificationStatus);
      params.set("sort_direction", activeFilters.sortDirection);
      setPending(await api.get<PendingItem[]>(`/api/work-orders/historical/pending-classification?${params.toString()}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron cargar las OT pendientes.");
    } finally {
      setLoadingPending(false);
    }
  }

  useEffect(() => {
    void api.get<Worker[]>("/api/users/workers").then(setWorkers).catch(() => setWorkers([]));
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadPending(filters); }, 250);
    return () => window.clearTimeout(timer);
  }, [filters]);

  function updateFilter<K extends keyof PendingFilters>(key: K, value: PendingFilters[K]) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function clearFilters() {
    setFilters(emptyFilters);
  }

  async function chooseFile(file: File) {
    setError("");
    setNotice("");
    setItems([]);
    try {
      const parsed = await parseWorkbook(file);
      setItems(parsed);
      setNotice(`Planilla validada: ${parsed.length} registros listos para importar.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo leer la planilla.");
    }
  }

  async function importItems() {
    if (!items.length || busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api.post<ImportResult>("/api/work-orders/historical/import", { items });
      setItems([]);
      setNotice(`Importacion terminada: ${result.created} creadas${result.skipped ? `, ${result.skipped} omitidas por duplicado` : ""}. Quedaron pendientes de clasificacion.`);
      await loadPending(filters);
      if (result.unmatched_responsibles.length) {
        setNotice((current) => `${current} Revisa estos nombres no reconocidos: ${result.unmatched_responsibles.join(", ")}.`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo importar la planilla.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <section className="rounded-lg border bg-card p-4">
        <div className="flex items-start gap-3">
          <FileSpreadsheet className="mt-0.5 h-5 w-5 text-primary" />
          <div className="min-w-0 flex-1">
            <h3 className="font-semibold">Importar OT historicas desde Excel</h3>
            <p className="mt-1 text-sm text-muted-foreground">El equipo intervenido sera el titulo. Area, seccion y equipo del catalogo antiguo se asignan despues.</p>
            <label className="mt-3 inline-flex cursor-pointer items-center rounded-md border bg-background px-3 py-2 text-sm font-medium hover:bg-muted">
              <Upload className="mr-2 h-4 w-4" /> Seleccionar planilla
              <input type="file" accept=".xlsx,.xls" className="sr-only" disabled={busy} onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void chooseFile(file); }} />
            </label>
          </div>
        </div>
        {error && <p className="mt-3 rounded-md bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}
        {notice && <p className="mt-3 rounded-md bg-emerald-50 p-2 text-sm text-emerald-800">{notice}</p>}
        {items.length > 0 && (
          <div className="mt-4 rounded-md border p-3">
            <p className="text-sm font-medium">Vista previa: {items.length} registros</p>
            <div className="mt-2 max-h-48 overflow-auto text-xs">
              {items.slice(0, 8).map((item) => <div key={item.source_row} className="border-b py-1 last:border-0">Fila {item.source_row}: {item.title} - {item.duration_text || `${item.duration_minutes} min`} - {item.execution_date}</div>)}
              {items.length > 8 && <p className="pt-2 text-muted-foreground">... y {items.length - 8} registros mas.</p>}
            </div>
            <Button className="mt-3" onClick={() => void importItems()} disabled={busy}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Importar registros</Button>
          </div>
        )}
      </section>

      <section className="rounded-lg border bg-card p-4">
        <div className="flex items-center justify-between gap-3">
          <div><h3 className="font-semibold">OT históricas para clasificar</h3><p className="text-sm text-muted-foreground">Los filtros consultan todas las OTs históricas guardadas, no solo las filas visibles.</p></div>
          <span className="rounded-full bg-amber-100 px-2.5 py-1 text-sm font-medium text-amber-800">{pending.length}</span>
        </div>
        <div className="mt-4 rounded-md border bg-muted/20 p-3">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium"><SlidersHorizontal className="h-4 w-4 text-primary" />Filtros de clasificación</div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <label className="relative xl:col-span-2">
              <span className="sr-only">Buscar OT</span>
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <input className="h-9 w-full rounded-md border bg-background pl-9 pr-3 text-sm" placeholder="OT, título, equipo o descripción" value={filters.search} onChange={(event) => updateFilter("search", event.target.value)} />
            </label>
            <label>
              <span className="mb-1 block text-xs text-muted-foreground">Fecha desde</span>
              <input type="date" className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={filters.dateFrom} onChange={(event) => updateFilter("dateFrom", event.target.value)} />
            </label>
            <label>
              <span className="mb-1 block text-xs text-muted-foreground">Fecha hasta</span>
              <input type="date" className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={filters.dateTo} onChange={(event) => updateFilter("dateTo", event.target.value)} />
            </label>
            <label>
              <span className="mb-1 block text-xs text-muted-foreground">Responsable</span>
              <select className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={filters.responsibleUserId} onChange={(event) => updateFilter("responsibleUserId", event.target.value)}>
                <option value="">Todos</option>
                {workers.map((worker) => <option key={worker.id} value={worker.id}>{worker.full_name}</option>)}
              </select>
            </label>
            <label>
              <span className="mb-1 block text-xs text-muted-foreground">Clasificación</span>
              <select className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={filters.classificationStatus} onChange={(event) => updateFilter("classificationStatus", event.target.value as ClassificationStatus)}>
                <option value="PENDING">Pendientes</option>
                <option value="WITHOUT_AREA">Sin área</option>
                <option value="WITHOUT_SECTION">Sin sección</option>
                <option value="WITHOUT_EQUIPMENT">Sin equipo</option>
                <option value="COMPLETE">Completas</option>
                <option value="ALL">Todas</option>
              </select>
            </label>
            <label>
              <span className="mb-1 block text-xs text-muted-foreground">Ordenar fecha</span>
              <select className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={filters.sortDirection} onChange={(event) => updateFilter("sortDirection", event.target.value as "asc" | "desc")}>
                <option value="asc">Más antiguas primero</option>
                <option value="desc">Más recientes primero</option>
              </select>
            </label>
          </div>
          {(filters.search || filters.dateFrom || filters.dateTo || filters.responsibleUserId || filters.classificationStatus !== "PENDING" || filters.sortDirection !== "asc") && (
            <button type="button" className="mt-3 inline-flex items-center gap-1 text-sm text-primary hover:underline" onClick={clearFilters}><X className="h-4 w-4" />Limpiar filtros</button>
          )}
        </div>
        <p className="mt-3 text-sm text-muted-foreground">Mostrando {pending.length} resultado{pending.length === 1 ? "" : "s"}.</p>
        {loadingPending ? <div className="flex justify-center py-6"><Loader2 className="h-5 w-5 animate-spin" /></div> : pending.length === 0 ? <p className="py-5 text-sm text-muted-foreground">No hay resultados con los filtros seleccionados.</p> : (
          <div className="mt-3 overflow-auto"><table className="w-full text-left text-sm"><thead className="bg-muted text-xs uppercase text-muted-foreground"><tr><th className="px-2 py-2">OT interna</th><th className="px-2 py-2">OT original</th><th className="px-2 py-2">Título</th><th className="px-2 py-2">Fecha de ejecución</th><th className="px-2 py-2">Responsable</th><th className="px-2 py-2">Clasificación</th><th className="px-2 py-2" /></tr></thead><tbody>{pending.map((item) => <tr key={item.id} className="border-t"><td className="px-2 py-2 font-medium">{item.ot_number}</td><td className="px-2 py-2">{item.original_ot_number || "-"}</td><td className="px-2 py-2">{item.title}</td><td className="whitespace-nowrap px-2 py-2">{formatDateOnly(item.execution_date) || "-"}</td><td className="px-2 py-2">{item.responsible_user_name || "No asignado"}</td><td className="px-2 py-2"><span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${classificationClasses[item.classification_status]}`}>{classificationLabels[item.classification_status]}</span></td><td className="px-2 py-2 text-right"><Link className="text-primary hover:underline" href={`/ordenes/${item.id}`}>Clasificar</Link></td></tr>)}</tbody></table></div>
        )}
      </section>
    </div>
  );
}
