"use client";

import { useCallback, useEffect, useState } from "react";
import * as XLSX from "xlsx";
import { Check, FileSpreadsheet, Loader2, Pencil, Plus, Upload, X } from "lucide-react";
import { api } from "@/lib/api";
import type { MaterialCatalogItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type MaterialPage = { items: MaterialCatalogItem[]; total: number; families: string[] };
type ImportResult = { received: number; created: number; updated: number; skipped: number };
type Draft = { code: string; description: string; family: string };

function text(value: unknown) { return String(value ?? "").trim(); }
function normalized(value: unknown) {
  return text(value).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}
function familyFromSheet(sheetName: string, firstCell: unknown) {
  const title = text(firstCell) || sheetName;
  return title.replace(/^[A-Z]+\d+\s*[·:-]?\s*/i, "").trim() || sheetName;
}

function parseWorkbook(file: File): Promise<Array<{ code: string; description: string; family: string; source_sheet: string }>> {
  return file.arrayBuffer().then((buffer) => {
    const workbook = XLSX.read(buffer, { type: "array", cellDates: false });
    const items: Array<{ code: string; description: string; family: string; source_sheet: string }> = [];
    for (const sheetName of workbook.SheetNames) {
      const sheet = workbook.Sheets[sheetName];
      const rows = XLSX.utils.sheet_to_json<unknown[]>(sheet, { header: 1, defval: "", raw: false });
      const headerIndex = rows.findIndex((row) => {
        const headers = row.map(normalized);
        return headers.some((value) => value === "codigo") && headers.some((value) => value === "descripcion");
      });
      if (headerIndex < 0) continue;
      const headers = rows[headerIndex].map(normalized);
      const codeIndex = headers.findIndex((value) => value === "codigo");
      const descriptionIndex = headers.findIndex((value) => value === "descripcion");
      const family = familyFromSheet(sheetName, rows[0]?.[0]);
      for (const row of rows.slice(headerIndex + 1)) {
        const code = text(row[codeIndex]).toUpperCase();
        const description = text(row[descriptionIndex]);
        if (code && description) items.push({ code, description, family, source_sheet: sheetName });
      }
    }
    return items;
  });
}

export function MaterialCatalogManager() {
  const [page, setPage] = useState<MaterialPage>({ items: [], total: 0, families: [] });
  const [query, setQuery] = useState("");
  const [includeInactive, setIncludeInactive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [draft, setDraft] = useState<Draft>({ code: "", description: "", family: "" });
  const [editingId, setEditingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ query, include_inactive: String(includeInactive), limit: "5000", offset: "0" });
      setPage(await api.get<MaterialPage>(`/api/admin/materials?${params.toString()}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cargar el catálogo.");
    } finally { setLoading(false); }
  }, [includeInactive, query]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(timer);
  }, [load]);

  function clearMessages() { setError(""); setNotice(""); }

  async function saveManual() {
    clearMessages();
    if (!draft.code.trim() || !draft.description.trim() || !draft.family.trim()) {
      setError("Completa código, descripción y familia."); return;
    }
    setBusy("manual");
    try {
      if (editingId) {
        await api.patch(`/api/admin/materials/${editingId}`, { description: draft.description, family: draft.family });
        setNotice("Material actualizado.");
      } else {
        await api.post("/api/admin/materials", draft);
        setNotice("Material creado.");
      }
      setDraft({ code: "", description: "", family: "" }); setEditingId(null); await load();
    } catch (err) { setError(err instanceof Error ? err.message : "No se pudo guardar el material."); }
    finally { setBusy(""); }
  }

  async function toggleActive(material: MaterialCatalogItem) {
    clearMessages(); setBusy(`toggle-${material.id}`);
    try {
      await api.patch(`/api/admin/materials/${material.id}`, { active: !material.active });
      setNotice(material.active ? "Material desactivado." : "Material activado."); await load();
    } catch (err) { setError(err instanceof Error ? err.message : "No se pudo cambiar el estado."); }
    finally { setBusy(""); }
  }

  async function importFile(file: File) {
    clearMessages(); setBusy("import");
    try {
      const items = await parseWorkbook(file);
      if (!items.length) throw new Error("No encontré hojas con columnas Código y Descripción.");
      const result = await api.post<ImportResult>("/api/admin/materials/import", { items });
      setNotice(`Importación terminada: ${result.created} creados, ${result.updated} actualizados${result.skipped ? ` y ${result.skipped} omitidos` : ""}.`);
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : "No se pudo importar la planilla."); }
    finally { setBusy(""); }
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="mb-1 text-lg font-semibold">Catálogo de materiales</h3>
        <p className="text-sm text-muted-foreground">Administra códigos y descripciones. No registra cantidades ni stock; solo permite seleccionarlos en las OTs.</p>
      </div>
      {error && <p className="rounded-md bg-destructive/5 p-2 text-sm text-destructive">{error}</p>}
      {notice && <p className="rounded-md bg-emerald-50 p-2 text-sm text-emerald-800">{notice}</p>}

      <div className="rounded-lg border bg-card p-4">
        <div className="flex items-start gap-3">
          <FileSpreadsheet className="mt-0.5 h-5 w-5 text-primary" />
          <div className="min-w-0 flex-1">
            <h4 className="font-medium">Importar planilla Excel</h4>
            <p className="mt-1 text-xs text-muted-foreground">Lee todas las hojas que tengan las columnas Código y Descripción. La familia se toma del nombre de la hoja.</p>
            <label className="mt-3 inline-flex cursor-pointer items-center rounded-md border bg-background px-3 py-2 text-sm font-medium hover:bg-muted">
              {busy === "import" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}
              Seleccionar Excel
              <input type="file" accept=".xlsx,.xls,.csv" className="sr-only" disabled={busy !== ""} onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void importFile(file); }} />
            </label>
          </div>
        </div>
      </div>

      <div className="rounded-lg border bg-card p-4">
        <h4 className="mb-3 font-medium">{editingId ? "Editar material" : "Agregar material"}</h4>
        <div className="grid gap-2 md:grid-cols-[180px_1fr_220px_auto]">
          <Input placeholder="Código" value={draft.code} disabled={editingId !== null} onChange={(event) => setDraft((current) => ({ ...current, code: event.target.value }))} />
          <Input placeholder="Descripción" value={draft.description} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} />
          <Input placeholder="Familia" value={draft.family} onChange={(event) => setDraft((current) => ({ ...current, family: event.target.value }))} />
          <div className="flex gap-2">
            <Button onClick={() => void saveManual()} disabled={busy === "manual"}>{busy === "manual" ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Plus className="mr-1 h-4 w-4" />}{editingId ? "Guardar" : "Agregar"}</Button>
            {editingId && <Button variant="outline" onClick={() => { setEditingId(null); setDraft({ code: "", description: "", family: "" }); }}><X /></Button>}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input className="max-w-md" placeholder="Buscar código, descripción o familia" value={query} onChange={(event) => setQuery(event.target.value)} />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={includeInactive} onChange={(event) => setIncludeInactive(event.target.checked)} />Mostrar inactivos</label>
        <span className="text-sm text-muted-foreground">{page.total} materiales</span>
      </div>

      <div className="overflow-hidden rounded-lg border">
        {loading ? <div className="flex justify-center py-10"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div> : page.items.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No hay materiales que mostrar.</p> : (
          <div className="max-h-[520px] overflow-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-muted/90 text-xs uppercase text-muted-foreground"><tr><th className="px-3 py-2">Código</th><th className="px-3 py-2">Descripción</th><th className="px-3 py-2">Familia</th><th className="px-3 py-2">Estado</th><th className="px-3 py-2" /></tr></thead>
              <tbody>{page.items.map((material) => <tr key={material.id} className="border-t align-top"><td className="px-3 py-2 font-medium">{material.code}</td><td className="px-3 py-2">{material.description}</td><td className="px-3 py-2 text-muted-foreground">{material.family}</td><td className="px-3 py-2">{material.active ? "Activo" : "Inactivo"}</td><td className="px-3 py-2"><div className="flex gap-1"><Button size="icon" variant="ghost" aria-label="Editar material" onClick={() => { setEditingId(material.id); setDraft({ code: material.code, description: material.description, family: material.family }); }}><Pencil className="h-4 w-4" /></Button><Button size="sm" variant="outline" onClick={() => void toggleActive(material)} disabled={busy === `toggle-${material.id}`}>{busy === `toggle-${material.id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : material.active ? "Desactivar" : <><Check className="mr-1 h-4 w-4" />Activar</>}</Button></div></td></tr>)}</tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
