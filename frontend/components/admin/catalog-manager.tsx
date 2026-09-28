"use client";

import { useCallback, useEffect, useState } from "react";
import * as XLSX from "xlsx";
import { Check, FileSpreadsheet, Loader2, Pencil, Plus, Trash2, Upload, X } from "lucide-react";
import { api } from "@/lib/api";
import type { AreaNode, EquipmentNode, InventoryImportResult } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type InventoryImportItem = {
  inventory_code: string;
  plant_area: string;
  section: string;
  equipment: string;
  category?: string;
  location?: string;
  operational_status?: string;
};

function normalizeHeader(value: unknown) {
  return String(value ?? "").trim().normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase();
}

function cellText(value: unknown) {
  return String(value ?? "").trim();
}

async function parseInventoryWorkbook(file: File): Promise<InventoryImportItem[]> {
  const workbook = XLSX.read(await file.arrayBuffer(), { type: "array", raw: false });
  const sheetName = workbook.SheetNames.find((name) => normalizeHeader(name) === "INVENTARIO") || workbook.SheetNames[0];
  const rows = XLSX.utils.sheet_to_json<unknown[]>(workbook.Sheets[sheetName], { header: 1, defval: "", raw: false });
  const headerIndex = rows.findIndex((row) => {
    const headers = row.map(normalizeHeader);
    return ["ID", "AREA", "SECCION", "ARTICULO"].every((header) => headers.includes(header));
  });
  if (headerIndex < 0) throw new Error("No encontré las columnas ID, AREA, SECCION y ARTICULO.");
  const headers = rows[headerIndex].map(normalizeHeader);
  const index = (name: string) => headers.indexOf(name);
  const items: InventoryImportItem[] = [];
  for (const row of rows.slice(headerIndex + 1)) {
    const inventory_code = cellText(row[index("ID")]);
    const plant_area = cellText(row[index("AREA")]);
    const section = cellText(row[index("SECCION")]);
    const equipment = cellText(row[index("ARTICULO")]);
    if (!inventory_code && !plant_area && !section && !equipment) continue;
    items.push({
      inventory_code,
      plant_area,
      section,
      equipment,
      category: index("CATEGORIA") >= 0 ? cellText(row[index("CATEGORIA")]) : "",
      location: index("UBICACION") >= 0 ? cellText(row[index("UBICACION")]) : "",
      operational_status: index("ESTADO OPERATIVIDAD") >= 0 ? cellText(row[index("ESTADO OPERATIVIDAD")]) : "",
    });
  }
  return items;
}

/** Admin management for OT sections and their equipment catalog. */
export function CatalogManager() {
  const [areas, setAreas] = useState<AreaNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [newArea, setNewArea] = useState("");
  const [newEquipment, setNewEquipment] = useState("");
  const [activeArea, setActiveArea] = useState<number | null>(null);
  const [editingAreaId, setEditingAreaId] = useState<number | null>(null);
  const [areaDraft, setAreaDraft] = useState("");
  const [editingEquipmentId, setEditingEquipmentId] = useState<number | null>(null);
  const [equipmentDraft, setEquipmentDraft] = useState("");
  const [busy, setBusy] = useState("");
  const [importing, setImporting] = useState(false);
  const [importMessage, setImportMessage] = useState("");
  const [importError, setImportError] = useState("");

  const load = useCallback(async () => {
    try {
      setAreas(await api.getCached<AreaNode[]>("/api/catalogs/tree", 5 * 60 * 1000));
    } catch {
      setAreas([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function fail(err: unknown, fallback: string) {
    setError(err instanceof Error ? err.message : fallback);
  }

  async function addArea() {
    if (!newArea.trim()) return;
    setError("");
    try {
      await api.post("/api/catalogs/areas", { name: newArea.trim() });
      setNewArea("");
      api.invalidateCache("/api/catalogs/tree");
      await load();
    } catch (err) {
      fail(err, "Error al crear la sección");
    }
  }

  async function addEquipment(areaId: number) {
    if (!newEquipment.trim()) return;
    setError("");
    try {
      await api.post("/api/catalogs/equipment", { name: newEquipment.trim(), area_id: areaId });
      setNewEquipment("");
      api.invalidateCache("/api/catalogs/tree");
      await load();
    } catch (err) {
      fail(err, "Error al crear el tipo de equipo");
    }
  }

  function startAreaEdit(area: AreaNode) {
    setError("");
    setEditingAreaId(area.id);
    setAreaDraft(area.name);
  }

  async function saveArea(areaId: number) {
    if (!areaDraft.trim()) return;
    setBusy(`area-${areaId}`);
    setError("");
    try {
      await api.patch(`/api/catalogs/areas/${areaId}`, { name: areaDraft.trim() });
      setEditingAreaId(null);
      api.invalidateCache("/api/catalogs/tree");
      await load();
    } catch (err) {
      fail(err, "Error al editar la sección");
    } finally {
      setBusy("");
    }
  }

  async function removeArea(area: AreaNode) {
    if (!window.confirm(`¿Eliminar la sección "${area.name}"?`)) return;
    setBusy(`delete-area-${area.id}`);
    setError("");
    try {
      await api.del(`/api/catalogs/areas/${area.id}`);
      if (activeArea === area.id) setActiveArea(null);
      api.invalidateCache("/api/catalogs/tree");
      await load();
    } catch (err) {
      fail(err, "No se pudo eliminar la sección");
    } finally {
      setBusy("");
    }
  }

  function startEquipmentEdit(equipment: EquipmentNode) {
    setError("");
    setEditingEquipmentId(equipment.id);
    setEquipmentDraft(equipment.name);
  }

  async function saveEquipment(equipmentId: number) {
    if (!equipmentDraft.trim()) return;
    setBusy(`equipment-${equipmentId}`);
    setError("");
    try {
      await api.patch(`/api/catalogs/equipment/${equipmentId}`, { name: equipmentDraft.trim() });
      setEditingEquipmentId(null);
      api.invalidateCache("/api/catalogs/tree");
      await load();
    } catch (err) {
      fail(err, "Error al editar el tipo de equipo");
    } finally {
      setBusy("");
    }
  }

  async function removeEquipment(equipment: EquipmentNode) {
    if (!window.confirm(`¿Eliminar el tipo de equipo "${equipment.name}"?`)) return;
    setBusy(`delete-equipment-${equipment.id}`);
    setError("");
    try {
      await api.del(`/api/catalogs/equipment/${equipment.id}`);
      api.invalidateCache("/api/catalogs/tree");
      await load();
    } catch (err) {
      fail(err, "No se pudo eliminar el tipo de equipo");
    } finally {
      setBusy("");
    }
  }

  async function importInventory(file: File) {
    setImporting(true);
    setImportMessage("");
    setImportError("");
    try {
      const items = await parseInventoryWorkbook(file);
      if (!items.length) throw new Error("La hoja Inventario no contiene registros.");
      const result = await api.post<InventoryImportResult>("/api/catalogs/inventory/import", { items });
      setImportMessage(
        `Importación lista: ${result.equipment_created} equipos nuevos, ${result.equipment_updated} actualizados, ${result.sections_created} secciones nuevas y ${result.skipped} omitidos.`
      );
      if (result.errors.length) setImportError(result.errors.slice(0, 5).join(" "));
      api.invalidateCache("/api/catalogs/tree");
      api.invalidateCache("/api/catalogs/hierarchy");
      await load();
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "No se pudo importar el inventario.");
    } finally {
      setImporting(false);
    }
  }

  if (loading) {
    return <div className="flex justify-center py-10"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>;
  }

  return (
    <div>
      <h3 className="mb-1 text-lg font-semibold">Catálogo</h3>
      <p className="mb-4 text-sm text-muted-foreground">Secciones → Equipos. Cada sección determina los equipos disponibles para una OT.</p>

      <div className="mb-4 rounded-lg border bg-card p-4">
        <div className="flex items-start gap-3">
          <FileSpreadsheet className="mt-0.5 h-5 w-5 text-primary" />
          <div className="min-w-0 flex-1">
            <h4 className="font-semibold">Importar inventario con área y sección</h4>
            <p className="mb-3 text-sm text-muted-foreground">
              Usa la hoja Inventario. Los equipos se identifican por su ID y no se borran los registros actuales.
            </p>
            <label className="inline-flex cursor-pointer items-center rounded-md border px-3 py-2 text-sm font-medium hover:bg-muted">
              <Upload className="mr-2 h-4 w-4" />
              {importing ? "Importando..." : "Seleccionar Excel"}
              <input
                type="file"
                accept=".xlsx,.xls"
                className="hidden"
                disabled={importing}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) void importInventory(file);
                }}
              />
            </label>
            {importMessage && <p className="mt-2 text-sm text-emerald-700">{importMessage}</p>}
            {importError && <p className="mt-2 text-sm text-destructive">{importError}</p>}
          </div>
        </div>
      </div>

      {error && <p className="mb-3 rounded-md bg-destructive/5 p-2 text-sm text-destructive">{error}</p>}

      <div className="mb-4 flex gap-2 rounded-lg border bg-card p-3">
        <Input placeholder="Nueva sección (ej: Horno)" value={newArea} onChange={(event) => setNewArea(event.target.value)} className="h-10" />
        <Button size="sm" onClick={addArea}><Plus className="mr-1 h-4 w-4" />Agregar</Button>
      </div>

      <div className="space-y-2">
        {areas.map((area) => (
          <div key={area.id} className="rounded-lg border bg-card">
            <div className="flex items-center gap-2 p-3">
              {editingAreaId === area.id ? (
                <>
                  <Input value={areaDraft} onChange={(event) => setAreaDraft(event.target.value)} className="h-9 flex-1" />
                  <Button size="icon" variant="ghost" onClick={() => saveArea(area.id)} disabled={busy === `area-${area.id}`} aria-label="Guardar área">
                    {busy === `area-${area.id}` ? <Loader2 className="animate-spin" /> : <Check />}
                  </Button>
                  <Button size="icon" variant="ghost" onClick={() => setEditingAreaId(null)} aria-label="Cancelar edición"><X /></Button>
                </>
              ) : (
                <button onClick={() => setActiveArea(activeArea === area.id ? null : area.id)} className="flex min-w-0 flex-1 items-center justify-between text-left font-semibold hover:text-primary">
                  <span>{area.name}</span>
                  <span className="text-xs font-normal text-muted-foreground">{area.equipment.length} tipos de equipo</span>
                </button>
              )}
              {editingAreaId !== area.id && (
                <>
                  <Button size="icon" variant="ghost" onClick={() => startAreaEdit(area)} aria-label="Editar área"><Pencil /></Button>
                  <Button size="icon" variant="ghost" onClick={() => removeArea(area)} disabled={busy === `delete-area-${area.id}`} aria-label="Eliminar área">
                    {busy === `delete-area-${area.id}` ? <Loader2 className="animate-spin" /> : <Trash2 />}
                  </Button>
                </>
              )}
            </div>

            {activeArea === area.id && editingAreaId !== area.id && (
              <div className="space-y-2 border-t p-3">
                <div className="max-h-56 space-y-1 overflow-y-auto pr-1">
                  {area.equipment.length === 0 ? (
                    <p className="px-2 py-1 text-sm text-muted-foreground">Sin tipos de equipo todavía.</p>
                  ) : area.equipment.map((equipment) => (
                    <div key={equipment.id} className="flex items-center gap-1 rounded px-2 py-1 text-sm">
                      {editingEquipmentId === equipment.id ? (
                        <>
                          <Input value={equipmentDraft} onChange={(event) => setEquipmentDraft(event.target.value)} className="h-8 flex-1" />
                          <Button size="icon" variant="ghost" onClick={() => saveEquipment(equipment.id)} disabled={busy === `equipment-${equipment.id}`} aria-label="Guardar equipo">
                            {busy === `equipment-${equipment.id}` ? <Loader2 className="animate-spin" /> : <Check />}
                          </Button>
                          <Button size="icon" variant="ghost" onClick={() => setEditingEquipmentId(null)} aria-label="Cancelar edición"><X /></Button>
                        </>
                      ) : (
                        <>
                          <span className="flex-1">{equipment.name}{equipment.inventory_code ? ` — ID ${equipment.inventory_code}` : ""}</span>
                          <Button size="icon" variant="ghost" onClick={() => startEquipmentEdit(equipment)} aria-label="Editar tipo de equipo"><Pencil /></Button>
                          <Button size="icon" variant="ghost" onClick={() => removeEquipment(equipment)} disabled={busy === `delete-equipment-${equipment.id}`} aria-label="Eliminar tipo de equipo">
                            {busy === `delete-equipment-${equipment.id}` ? <Loader2 className="animate-spin" /> : <Trash2 />}
                          </Button>
                        </>
                      )}
                    </div>
                  ))}
                </div>
                <div className="flex gap-2 pt-2">
                  <Input placeholder="Tipo de equipo (ej: Filtro)" value={newEquipment} onChange={(event) => setNewEquipment(event.target.value)} className="h-9" />
                  <Button size="sm" variant="outline" onClick={() => addEquipment(area.id)}>Agregar</Button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
