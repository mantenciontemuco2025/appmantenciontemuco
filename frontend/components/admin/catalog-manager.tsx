"use client";

import { useCallback, useEffect, useState } from "react";
import * as XLSX from "xlsx";
import { Check, Eye, EyeOff, FileSpreadsheet, Loader2, Pencil, Plus, Search, Trash2, Upload, X } from "lucide-react";
import { api } from "@/lib/api";
import type { AreaNode, EquipmentNode, InventoryImportResult, PlantAreaNode } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type InventoryImportItem = {
  inventory_code: string;
  plant_area: string;
  section: string;
  equipment: string;
  category: string | null;
  model: string | null;
  dimensions: string | null;
  weight: number | null;
  unit: string | null;
  description: string | null;
  location: string | null;
  purchase_receipt_date: string | null;
  purchased_from: string | null;
  warranty_end: string | null;
  web1: string | null;
  initial_value: number | null;
  impeller_diameter: string | null;
  flow_rate: string | null;
  total_manometric_head: string | null;
  rotation_speed: string | null;
  npsh: string | null;
  operational_status: string | null;
  general_spare_parts: string | null;
  observations: string | null;
  power_hp: string | null;
  power_kw: string | null;
  voltage: string | null;
  current: string | null;
  revolutions: string | null;
  efficiency: string | null;
  capacity: string | null;
};

function normalizeHeader(value: unknown) {
  return String(value ?? "").trim().normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase();
}

function cellText(value: unknown) {
  return String(value ?? "").trim();
}

function optionalCellText(value: unknown) {
  return cellText(value) || null;
}

function numericCell(value: unknown, label: string, rowNumber: number): number | null {
  if (value === null || value === undefined || cellText(value) === "") return null;
  if (typeof value === "number") {
    if (Number.isFinite(value)) return value;
    throw new Error(`Fila ${rowNumber}: el valor de ${label} no es numérico.`);
  }
  let text = cellText(value).replace(/\s/g, "");
  if (text.includes(",") && text.includes(".")) {
    text = text.lastIndexOf(",") > text.lastIndexOf(".")
      ? text.replace(/\./g, "").replace(",", ".")
      : text.replace(/,/g, "");
  } else if (text.includes(",")) {
    text = text.replace(",", ".");
  }
  const parsed = Number(text);
  if (!Number.isFinite(parsed)) throw new Error(`Fila ${rowNumber}: el valor de ${label} no es numérico.`);
  return parsed;
}

function dateCell(value: unknown, label: string, rowNumber: number): string | null {
  if (value === null || value === undefined || cellText(value) === "") return null;
  let year: number;
  let month: number;
  let day: number;
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    year = value.getFullYear();
    month = value.getMonth() + 1;
    day = value.getDate();
  } else if (typeof value === "number") {
    const parsed = XLSX.SSF.parse_date_code(value);
    if (!parsed) throw new Error(`Fila ${rowNumber}: fecha inválida en ${label}.`);
    ({ y: year, m: month, d: day } = parsed);
  } else {
    const text = cellText(value);
    const iso = text.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
    const local = text.match(/^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})$/);
    if (iso) {
      year = Number(iso[1]); month = Number(iso[2]); day = Number(iso[3]);
    } else if (local) {
      day = Number(local[1]); month = Number(local[2]); year = Number(local[3]);
    } else {
      throw new Error(`Fila ${rowNumber}: fecha inválida en ${label} (${text}).`);
    }
  }
  const date = new Date(Date.UTC(year, month - 1, day));
  if (year < 1900 || year > 2100 || date.getUTCFullYear() !== year || date.getUTCMonth() + 1 !== month || date.getUTCDate() !== day) {
    throw new Error(`Fila ${rowNumber}: revisa la fecha de ${label}; debe estar entre 1900 y 2100.`);
  }
  return `${year.toString().padStart(4, "0")}-${month.toString().padStart(2, "0")}-${day.toString().padStart(2, "0")}`;
}

function normalizeCatalogSearch(value: string) {
  return value.trim().normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase();
}

type CatalogSearchResult = {
  key: string;
  label: string;
  kind: "Área" | "Sección" | "Equipo";
  path: string;
  targetId: string;
  plantAreaId?: number;
  legacySectionId?: number;
  plantAreaSectionKey?: string;
};

const VISIBLE_EQUIPMENT_PREVIEW = 4;

async function parseInventoryWorkbook(file: File): Promise<InventoryImportItem[]> {
  const workbook = XLSX.read(await file.arrayBuffer(), { type: "array", raw: false });
  const sheetName = workbook.SheetNames.find((name) => normalizeHeader(name) === "INVENTARIO") || workbook.SheetNames[0];
  const rows = XLSX.utils.sheet_to_json<unknown[]>(workbook.Sheets[sheetName], { header: 1, defval: "", raw: true });
  const headerIndex = rows.findIndex((row) => {
    const headers = row.map(normalizeHeader);
    return ["ID", "AREA", "SECCION", "ARTICULO"].every((header) => headers.includes(header));
  });
  if (headerIndex < 0) throw new Error("No encontré las columnas ID, AREA, SECCION y ARTICULO.");
  const headers = rows[headerIndex].map(normalizeHeader);
  const index = (name: string) => headers.indexOf(normalizeHeader(name));
  const items: InventoryImportItem[] = [];
  const issues: string[] = [];
  const seenCodes = new Set<string>();
  const get = (row: unknown[], column: string) => index(column) >= 0 ? row[index(column)] : null;
  for (let rowIndex = headerIndex + 1; rowIndex < rows.length; rowIndex += 1) {
    const row = rows[rowIndex];
    const rowNumber = rowIndex + 1;
    if (row.every((value) => value === null || value === undefined || cellText(value) === "")) continue;
    const inventory_code = cellText(get(row, "ID"));
    const plant_area = cellText(get(row, "AREA"));
    const section = cellText(get(row, "SECCION"));
    const equipment = cellText(get(row, "ARTICULO"));
    if (!inventory_code || !plant_area || !section || !equipment) {
      issues.push(`Fila ${rowNumber}: ID, AREA, SECCION y ARTICULO son obligatorios.`);
      continue;
    }
    const normalizedCode = inventory_code.toLocaleUpperCase();
    if (seenCodes.has(normalizedCode)) {
      issues.push(`Fila ${rowNumber}: el ID ${inventory_code} está repetido en la planilla.`);
      continue;
    }
    seenCodes.add(normalizedCode);
    try {
      items.push({
        inventory_code,
        plant_area,
        section,
        equipment,
        category: optionalCellText(get(row, "CATEGORIA")),
        model: optionalCellText(get(row, "MODELO")),
        dimensions: optionalCellText(get(row, "DIMENSIONES")),
        weight: numericCell(get(row, "PESO"), "PESO", rowNumber),
        unit: optionalCellText(get(row, "UNIDAD")),
        description: optionalCellText(get(row, "DESCRIPCION")),
        location: optionalCellText(get(row, "UBICACION")),
        purchase_receipt_date: dateCell(get(row, "FECHA COMPRA/RECEPCION"), "FECHA COMPRA/RECEPCION", rowNumber),
        purchased_from: optionalCellText(get(row, "COMPRADO EN/FUENTE")),
        warranty_end: dateCell(get(row, "FIN GARANTIA"), "FIN GARANTIA", rowNumber),
        web1: optionalCellText(get(row, "WEB1")),
        initial_value: numericCell(get(row, "VALOR INICIAL"), "VALOR INICIAL", rowNumber),
        impeller_diameter: optionalCellText(get(row, "DIAMETRO RODETE")),
        flow_rate: optionalCellText(get(row, "CAUDAL (Q)")),
        total_manometric_head: optionalCellText(get(row, "ALTURA MANOMETRICA TOTAL (AMT O H)")),
        rotation_speed: optionalCellText(get(row, "VEL. GIRO (N)")),
        npsh: optionalCellText(get(row, "NPSH")),
        operational_status: optionalCellText(get(row, "ESTADO OPERATIVIDAD")),
        general_spare_parts: optionalCellText(get(row, "REPUESTOS GENERALES")),
        observations: optionalCellText(get(row, "OBSERVACIONES")),
        power_hp: optionalCellText(get(row, "POTENCIA/HP")),
        power_kw: optionalCellText(get(row, "POTENCIA/KW")),
        voltage: optionalCellText(get(row, "VOLTAJE")),
        current: optionalCellText(get(row, "CORRIENTE")),
        revolutions: optionalCellText(get(row, "REVOLUCIONES")),
        efficiency: optionalCellText(get(row, "EFICIENCIA")),
        capacity: optionalCellText(get(row, "CAPACIDAD")),
      });
    } catch (error) {
      issues.push(error instanceof Error ? error.message : `Fila ${rowNumber}: hay un dato inválido.`);
    }
  }
  if (issues.length) throw new Error(`Corrige la planilla antes de importarla:\n${issues.slice(0, 8).join(" ")}${issues.length > 8 ? ` Hay ${issues.length - 8} observaciones más.` : ""}`);
  return items;
}

/** Admin management for OT sections and their equipment catalog. */
export function CatalogManager() {
  const [areas, setAreas] = useState<AreaNode[]>([]);
  const [plantAreas, setPlantAreas] = useState<PlantAreaNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [newArea, setNewArea] = useState("");
  const [areaMessage, setAreaMessage] = useState("");
  const [newPlantArea, setNewPlantArea] = useState("");
  const [plantAreaMessage, setPlantAreaMessage] = useState("");
  const [editingPlantAreaId, setEditingPlantAreaId] = useState<number | null>(null);
  const [plantAreaDraft, setPlantAreaDraft] = useState("");
  const [viewingPlantAreaId, setViewingPlantAreaId] = useState<number | null>(null);
  const [expandedPlantAreaId, setExpandedPlantAreaId] = useState<number | null>(null);
  const [expandedEquipmentSections, setExpandedEquipmentSections] = useState<Record<string, boolean>>({});
  const [catalogSearch, setCatalogSearch] = useState("");
  const [sectionSearch, setSectionSearch] = useState("");
  const [sectionLinkDrafts, setSectionLinkDrafts] = useState<Record<number, string>>({});
  const [equipmentLocationDrafts, setEquipmentLocationDrafts] = useState<Record<number, { plantAreaId: string; sectionId: string }>>({});
  const [newSectionDrafts, setNewSectionDrafts] = useState<Record<number, string>>({});
  const [newEquipmentDrafts, setNewEquipmentDrafts] = useState<Record<string, string>>({});
  const [plantAreaOrders, setPlantAreaOrders] = useState<Record<number, { id: number; ot_number: string; title: string; status: string; execution_date: string | null }[]>>({});
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
    const [tree, hierarchy] = await Promise.allSettled([
      api.getCached<AreaNode[]>("/api/catalogs/tree", 5 * 60 * 1000),
      api.getCached<PlantAreaNode[]>("/api/catalogs/hierarchy?include_inactive=true", 5 * 60 * 1000),
    ]);
    setAreas(tree.status === "fulfilled" ? tree.value : []);
    setPlantAreas(hierarchy.status === "fulfilled" ? hierarchy.value : []);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function fail(err: unknown, fallback: string) {
    setError(err instanceof Error ? err.message : fallback);
  }

  function startPlantAreaEdit(area: PlantAreaNode) {
    setError("");
    setEditingPlantAreaId(area.id);
    setPlantAreaDraft(area.name);
  }

  async function savePlantArea(areaId: number) {
    if (!plantAreaDraft.trim()) return;
    setBusy(`plant-area-${areaId}`);
    setError("");
    try {
      await api.patch(`/api/catalogs/plant-areas/${areaId}`, { name: plantAreaDraft.trim() });
      setEditingPlantAreaId(null);
      api.invalidateCache("/api/catalogs/hierarchy");
      api.invalidateCache("/api/catalogs/plant-areas");
      await load();
      setPlantAreaMessage("Área general actualizada correctamente.");
    } catch (err) {
      fail(err, "No se pudo editar el área general");
    } finally {
      setBusy("");
    }
  }

  async function togglePlantAreaActive(plantArea: PlantAreaNode) {
    const nextActive = !plantArea.is_active;
    if (
      !nextActive &&
      !window.confirm(`¿Desactivar "${plantArea.name}"? Dejará de aparecer al crear nuevas OTs, pero se conservará en el historial.`)
    ) return;
    setBusy(`plant-area-active-${plantArea.id}`);
    setError("");
    try {
      await api.patch(`/api/catalogs/plant-areas/${plantArea.id}`, { is_active: nextActive });
      api.invalidateCache("/api/catalogs/hierarchy");
      api.invalidateCache("/api/catalogs/plant-areas");
      await load();
      setPlantAreaMessage(nextActive
        ? `"${plantArea.name}" quedó activa y aparecerá al crear OTs.`
        : `"${plantArea.name}" quedó desactivada. Sus OTs históricas se conservan.`);
    } catch (err) {
      fail(err, "No se pudo cambiar el estado del área.");
    } finally {
      setBusy("");
    }
  }

  async function removePlantArea(area: PlantAreaNode) {
    if (!window.confirm(`¿Eliminar el área general "${area.name}"?`)) return;
    setBusy(`delete-plant-area-${area.id}`);
    setError("");
    try {
      await api.del(`/api/catalogs/plant-areas/${area.id}`);
      api.invalidateCache("/api/catalogs/hierarchy");
      api.invalidateCache("/api/catalogs/plant-areas");
      await load();
      setPlantAreaMessage(`Área general "${area.name}" eliminada.`);
    } catch (err) {
      fail(err, "No se pudo eliminar el área general. Puede tener datos asociados.");
    } finally {
      setBusy("");
    }
  }

  async function togglePlantAreaOrders(areaId: number) {
    if (viewingPlantAreaId === areaId) {
      setViewingPlantAreaId(null);
      return;
    }
    setViewingPlantAreaId(areaId);
    if (plantAreaOrders[areaId]) return;
    try {
      const orders = await api.get<typeof plantAreaOrders[number]>(`/api/catalogs/plant-areas/${areaId}/work-orders`);
      setPlantAreaOrders((current) => ({ ...current, [areaId]: orders }));
    } catch (err) {
      fail(err, "No se pudieron cargar las OTs del área");
    }
  }

  async function addPlantArea() {
    if (!newPlantArea.trim()) return;
    setBusy("create-plant-area");
    setError("");
    setPlantAreaMessage("");
    try {
      await api.post("/api/catalogs/plant-areas", { name: newPlantArea.trim() });
      const createdName = newPlantArea.trim();
      setNewPlantArea("");
      api.invalidateCache("/api/catalogs/hierarchy");
      api.invalidateCache("/api/catalogs/plant-areas");
      await load();
      setPlantAreaMessage(`Área general "${createdName}" agregada correctamente.`);
    } catch (err) {
      fail(err, "Error al crear el área general");
    } finally {
      setBusy("");
    }
  }

  async function refreshHierarchy() {
    api.invalidateCache("/api/catalogs/tree");
    api.invalidateCache("/api/catalogs/hierarchy");
    await load();
  }

  async function createSectionForPlantArea(plantAreaId: number) {
    const name = (newSectionDrafts[plantAreaId] || "").trim();
    if (!name) return;
    setBusy(`section-create-${plantAreaId}`);
    setError("");
    try {
      const result = await api.post<{ section_id: number; section_name: string; created: boolean }>(
        `/api/catalogs/plant-areas/${plantAreaId}/sections`, { name },
      );
      setNewSectionDrafts((current) => ({ ...current, [plantAreaId]: "" }));
      setPlantAreaMessage(result.created ? `Sección "${result.section_name}" creada y vinculada.` : `Sección existente "${result.section_name}" vinculada.`);
      await refreshHierarchy();
    } catch (err) {
      fail(err, "No se pudo crear o vincular la sección.");
    } finally {
      setBusy("");
    }
  }

  async function linkExistingSection(plantAreaId: number) {
    const sectionId = Number(sectionLinkDrafts[plantAreaId]);
    if (!sectionId) return;
    setBusy(`section-link-${plantAreaId}`);
    setError("");
    try {
      await api.post(`/api/catalogs/plant-areas/${plantAreaId}/sections/${sectionId}`, {});
      const section = areas.find((item) => item.id === sectionId);
      setSectionLinkDrafts((current) => ({ ...current, [plantAreaId]: "" }));
      setPlantAreaMessage(`Sección "${section?.name || ""}" vinculada al área.`);
      await refreshHierarchy();
    } catch (err) {
      fail(err, "No se pudo vincular la sección.");
    } finally {
      setBusy("");
    }
  }

  async function unlinkSection(plantArea: PlantAreaNode, section: AreaNode) {
    if (!window.confirm(`¿Desvincular "${section.name}" de "${plantArea.name}"? No se borrará la sección ni se modificarán las OTs históricas.`)) return;
    setBusy(`section-unlink-${plantArea.id}-${section.id}`);
    setError("");
    try {
      await api.del(`/api/catalogs/plant-areas/${plantArea.id}/sections/${section.id}`);
      setPlantAreaMessage(`Sección "${section.name}" desvinculada. El historial de OTs permanece intacto.`);
      await refreshHierarchy();
    } catch (err) {
      fail(err, "No se pudo desvincular la sección.");
    } finally {
      setBusy("");
    }
  }

  async function createEquipmentForSection(plantAreaId: number, sectionId: number) {
    const draftKey = `${plantAreaId}:${sectionId}`;
    const name = (newEquipmentDrafts[draftKey] || "").trim();
    if (!name) return;
    setBusy(`equipment-create-${draftKey}`);
    setError("");
    try {
      await api.post("/api/catalogs/equipment", {
        name,
        area_id: sectionId,
        plant_area_id: plantAreaId,
      });
      setNewEquipmentDrafts((current) => ({ ...current, [draftKey]: "" }));
      await refreshHierarchy();
    } catch (err) {
      fail(err, "No se pudo agregar el equipo a la sección.");
    } finally {
      setBusy("");
    }
  }

  async function assignLegacyEquipment(equipment: EquipmentNode, currentSectionId: number) {
    const draft = equipmentLocationDrafts[equipment.id] || { plantAreaId: "", sectionId: String(currentSectionId) };
    if (!draft.plantAreaId || !draft.sectionId) return;
    setBusy(`equipment-location-${equipment.id}`);
    setError("");
    try {
      await api.patch(`/api/catalogs/equipment/${equipment.id}`, {
        plant_area_id: Number(draft.plantAreaId),
        area_id: Number(draft.sectionId),
      });
      setPlantAreaMessage(`Equipo "${equipment.name}" asignado. Las OTs históricas no se modificaron.`);
      setEquipmentLocationDrafts((current) => {
        const next = { ...current };
        delete next[equipment.id];
        return next;
      });
      await refreshHierarchy();
    } catch (err) {
      fail(err, "No se pudo asignar el equipo al área y sección.");
    } finally {
      setBusy("");
    }
  }

  async function addArea() {
    if (!newArea.trim()) return;
    setBusy("create-area");
    setError("");
    setAreaMessage("");
    try {
      await api.post("/api/catalogs/areas", { name: newArea.trim() });
      const createdName = newArea.trim();
      setNewArea("");
      api.invalidateCache("/api/catalogs/tree");
      await load();
      setAreaMessage(`Área "${createdName}" agregada correctamente.`);
    } catch (err) {
      fail(err, "Error al crear el área");
    } finally {
      setBusy("");
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

  const assignedSectionIds = new Set(plantAreas.flatMap((plantArea) => plantArea.sections.map((section) => section.id)));
  const unassignedSections = areas.filter((section) => !assignedSectionIds.has(section.id));
  const unassignedEquipmentSections = areas
    .map((section) => ({ ...section, equipment: section.equipment.filter((equipment) => equipment.plant_area_id == null) }))
    .filter((section) => section.equipment.length > 0);
  const sectionsLinkableToArea = (plantArea: PlantAreaNode) => unassignedSections.filter((section) =>
    !plantArea.sections.some((assigned) => normalizeCatalogSearch(assigned.name) === normalizeCatalogSearch(section.name))
  );
  const sortedPlantAreas = [...plantAreas].sort((a, b) => a.name.localeCompare(b.name, "es"));
  const sortedAreas = [...areas].sort((a, b) => a.name.localeCompare(b.name, "es"));
  const normalizedSectionSearch = normalizeCatalogSearch(sectionSearch);
  const filteredSections = sortedAreas.filter((section) =>
    !normalizedSectionSearch
    || normalizeCatalogSearch(section.name).includes(normalizedSectionSearch)
    || (section.plant_area_names || []).some((name) => normalizeCatalogSearch(name).includes(normalizedSectionSearch))
    || section.equipment.some((equipment) => normalizeCatalogSearch(`${equipment.name} ${equipment.inventory_code || ""}`).includes(normalizedSectionSearch))
  );
  const normalizedCatalogSearch = normalizeCatalogSearch(catalogSearch);
  const catalogSearchResults: CatalogSearchResult[] = normalizedCatalogSearch
    ? [
        ...plantAreas.flatMap((plantArea) => {
          const results: CatalogSearchResult[] = [];
          if (normalizeCatalogSearch(plantArea.name).includes(normalizedCatalogSearch)) {
            results.push({
              key: `plant-area-${plantArea.id}`,
              label: plantArea.name,
              kind: "Área",
              path: plantArea.name,
              targetId: `plant-area-${plantArea.id}`,
              plantAreaId: plantArea.id,
            });
          }
          for (const section of plantArea.sections) {
            const sectionTargetId = `plant-section-${plantArea.id}-${section.id}`;
            if (normalizeCatalogSearch(section.name).includes(normalizedCatalogSearch)) {
              results.push({
                key: `plant-section-${plantArea.id}-${section.id}`,
                label: section.name,
                kind: "Sección",
                path: `${plantArea.name} → ${section.name}`,
                targetId: sectionTargetId,
                plantAreaId: plantArea.id,
              });
            }
            for (const equipment of section.equipment) {
              if (!normalizeCatalogSearch(`${equipment.name} ${equipment.inventory_code || ""}`).includes(normalizedCatalogSearch)) continue;
              results.push({
                key: `plant-equipment-${plantArea.id}-${equipment.id}`,
                label: equipment.name,
                kind: "Equipo",
                path: `${plantArea.name} → ${section.name}${equipment.inventory_code ? ` → ID ${equipment.inventory_code}` : ""}`,
                targetId: `plant-equipment-${plantArea.id}-${equipment.id}`,
                plantAreaId: plantArea.id,
                plantAreaSectionKey: `${plantArea.id}:${section.id}`,
              });
            }
          }
          return results;
        }),
        ...unassignedSections.flatMap((section) => {
          const results: CatalogSearchResult[] = [];
          if (normalizeCatalogSearch(section.name).includes(normalizedCatalogSearch)) {
            results.push({
              key: `unassigned-section-${section.id}`,
              label: section.name,
              kind: "Sección",
              path: "Sin área general asignada",
              targetId: `legacy-section-${section.id}`,
              legacySectionId: section.id,
            });
          }
          return results;
        }),
        ...unassignedEquipmentSections.flatMap((section) => section.equipment
          .filter((equipment) => normalizeCatalogSearch(`${equipment.name} ${equipment.inventory_code || ""}`).includes(normalizedCatalogSearch))
          .map((equipment) => ({
            key: `unassigned-equipment-${section.id}-${equipment.id}`,
            label: equipment.name,
            kind: "Equipo" as const,
            path: `Sin área asignada → ${section.name}${equipment.inventory_code ? ` → ID ${equipment.inventory_code}` : ""}`,
            targetId: `legacy-equipment-${equipment.id}`,
            legacySectionId: section.id,
          }))),
      ].slice(0, 40)
    : [];

  function openCatalogSearchResult(result: CatalogSearchResult) {
    if (result.plantAreaId !== undefined) setExpandedPlantAreaId(result.plantAreaId);
    if (result.legacySectionId !== undefined) setActiveArea(result.legacySectionId);
    if (result.plantAreaSectionKey) {
      setExpandedEquipmentSections((current) => ({ ...current, [result.plantAreaSectionKey!]: true }));
    }
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        document.getElementById(result.targetId)?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    });
  }

  return (
    <div>
      <h3 className="mb-1 text-lg font-semibold">Áreas, secciones y equipos</h3>
      <p className="mb-4 text-sm text-muted-foreground">Organiza el catálogo como Área general → Sección → Equipo. Los cambios de catálogo no reescriben las OTs históricas.</p>

      <div className="mb-4 rounded-lg border bg-card p-4">
        <label htmlFor="catalog-hierarchy-search" className="mb-2 block font-semibold">Buscar en el catálogo</label>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            id="catalog-hierarchy-search"
            value={catalogSearch}
            onChange={(event) => setCatalogSearch(event.target.value)}
            placeholder="Escribe el nombre del equipo, código o sección"
            className="h-10 pl-9"
            autoComplete="off"
          />
        </div>
        {normalizedCatalogSearch && (
          <div className="mt-3 max-h-72 space-y-1 overflow-y-auto" aria-live="polite">
            {catalogSearchResults.length ? catalogSearchResults.map((result) => (
              <button
                key={result.key}
                type="button"
                onClick={() => openCatalogSearchResult(result)}
                className="flex w-full flex-col rounded-md border px-3 py-2 text-left hover:bg-muted sm:flex-row sm:items-center sm:gap-3"
              >
                <span className="w-20 shrink-0 text-xs font-semibold uppercase text-primary">{result.kind}</span>
                <span className="min-w-0 flex-1 font-medium">{result.label}</span>
                <span className="text-xs text-muted-foreground">{result.path}</span>
              </button>
            )) : <p className="px-2 py-3 text-sm text-muted-foreground">No encontré coincidencias por área, sección, equipo o código.</p>}
            {catalogSearchResults.length === 40 && <p className="px-2 pt-1 text-xs text-muted-foreground">Mostrando los primeros 40 resultados; afina la búsqueda para acotar.</p>}
          </div>
        )}
      </div>

      <div className="mb-4 rounded-lg border bg-card p-4">
        <div className="mb-2">
          <h4 className="font-semibold">Agregar un área general</h4>
          <p className="text-sm text-muted-foreground">Ejemplo: Planta Malta, Planta Cajón o Planta de Riles. Después podrás asignarle secciones y equipos.</p>
        </div>
        <div className="flex gap-2">
          <Input
            placeholder="Nombre del área general"
            value={newPlantArea}
            onChange={(event) => {
              setNewPlantArea(event.target.value);
              setPlantAreaMessage("");
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") void addPlantArea();
            }}
            className="h-10"
            disabled={busy === "create-plant-area"}
            aria-label="Nombre del área general"
          />
          <Button size="sm" onClick={() => void addPlantArea()} disabled={!newPlantArea.trim() || busy === "create-plant-area"}>
            {busy === "create-plant-area" ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Plus className="mr-1 h-4 w-4" />}
            {busy === "create-plant-area" ? "Guardando..." : "Agregar área"}
          </Button>
        </div>
        {plantAreaMessage && <p className="mt-2 text-sm text-emerald-700">{plantAreaMessage}</p>}
        {plantAreas.length > 0 && (
          <div className="mt-3 grid gap-2 xl:grid-cols-2">
            {sortedPlantAreas.map((plantArea) => (
              <div key={plantArea.id} id={`plant-area-${plantArea.id}`} className={`space-y-2 rounded-md border bg-muted/30 p-3 ${plantArea.is_active ? "" : "opacity-70"}`}>
                <div className="flex flex-wrap items-center gap-2">
                  {editingPlantAreaId === plantArea.id ? (
                    <>
                      <Input value={plantAreaDraft} onChange={(event) => setPlantAreaDraft(event.target.value)} className="h-9 flex-1" aria-label="Editar área general" />
                      <Button size="icon" variant="ghost" onClick={() => void savePlantArea(plantArea.id)} disabled={busy === `plant-area-${plantArea.id}`} aria-label="Guardar área general">
                        {busy === `plant-area-${plantArea.id}` ? <Loader2 className="animate-spin" /> : <Check />}
                      </Button>
                      <Button size="icon" variant="ghost" onClick={() => setEditingPlantAreaId(null)} aria-label="Cancelar edición"><X /></Button>
                    </>
                  ) : (
                    <>
                      <span className="flex-1 text-sm font-semibold">{plantArea.name}{!plantArea.is_active && <span className="ml-2 rounded bg-muted px-2 py-0.5 text-xs font-normal text-muted-foreground">Inactiva</span>}</span>
                      <Button size="sm" variant="outline" onClick={() => void togglePlantAreaActive(plantArea)} disabled={busy === `plant-area-active-${plantArea.id}`}>
                        {busy === `plant-area-active-${plantArea.id}` ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : plantArea.is_active ? <EyeOff className="mr-1 h-4 w-4" /> : <Eye className="mr-1 h-4 w-4" />}
                        {plantArea.is_active ? "Desactivar" : "Activar"}
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => setExpandedPlantAreaId(expandedPlantAreaId === plantArea.id ? null : plantArea.id)}>
                        {expandedPlantAreaId === plantArea.id ? "Ocultar jerarquía" : `Gestionar jerarquía (${plantArea.sections.length})`}
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => void togglePlantAreaOrders(plantArea.id)}>
                        {viewingPlantAreaId === plantArea.id ? "Ocultar OTs" : "Ver OTs"}
                      </Button>
                      <Button size="icon" variant="ghost" onClick={() => startPlantAreaEdit(plantArea)} aria-label="Editar área general"><Pencil /></Button>
                      <Button size="icon" variant="ghost" onClick={() => void removePlantArea(plantArea)} disabled={busy === `delete-plant-area-${plantArea.id}`} aria-label="Eliminar área general">
                        {busy === `delete-plant-area-${plantArea.id}` ? <Loader2 className="animate-spin" /> : <Trash2 />}
                      </Button>
                    </>
                  )}
                </div>
                {expandedPlantAreaId === plantArea.id && editingPlantAreaId !== plantArea.id && (
                  <div className="grid gap-3 border-t pt-3 sm:grid-cols-2">
                    {!plantArea.sections.length && <p className="text-sm text-muted-foreground">Aún no hay secciones vinculadas a esta área.</p>}
                    {[...plantArea.sections].sort((a, b) => a.name.localeCompare(b.name, "es")).map((section) => {
                      const draftKey = `${plantArea.id}:${section.id}`;
                      const equipmentExpanded = expandedEquipmentSections[draftKey] || section.equipment.length <= VISIBLE_EQUIPMENT_PREVIEW;
                      const visibleEquipment = equipmentExpanded
                        ? [...section.equipment].sort((a, b) => a.name.localeCompare(b.name, "es"))
                        : [...section.equipment].sort((a, b) => a.name.localeCompare(b.name, "es")).slice(0, VISIBLE_EQUIPMENT_PREVIEW);
                      return (
                        <div key={section.id} id={`plant-section-${plantArea.id}-${section.id}`} className="rounded-md border bg-background p-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="flex-1 font-medium">{section.name}</span>
                            <span className="text-xs text-muted-foreground">{section.equipment.length} equipos</span>
                            <Button size="sm" variant="ghost" onClick={() => void unlinkSection(plantArea, section)} disabled={busy === `section-unlink-${plantArea.id}-${section.id}`}>
                              {busy === `section-unlink-${plantArea.id}-${section.id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="mr-1 h-4 w-4" />}Desvincular
                            </Button>
                          </div>
                          <div className="mt-2 grid gap-1 sm:grid-cols-2">
                            {visibleEquipment.map((equipment) => <div key={equipment.id} id={`plant-equipment-${plantArea.id}-${equipment.id}`} title={`${equipment.name}${equipment.inventory_code ? ` · ID ${equipment.inventory_code}` : ""}`} className="min-w-0 truncate rounded bg-muted/40 px-2 py-1 text-sm">{equipment.name}{equipment.inventory_code ? ` · ID ${equipment.inventory_code}` : ""}</div>)}
                            {!section.equipment.length && <p className="px-2 py-1 text-xs text-muted-foreground">Sin equipos asociados a esta área.</p>}
                            {section.equipment.length > VISIBLE_EQUIPMENT_PREVIEW && (
                              <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                className="h-8 px-2 text-xs"
                                aria-expanded={equipmentExpanded}
                                onClick={() => setExpandedEquipmentSections((current) => ({ ...current, [draftKey]: !equipmentExpanded }))}
                              >
                                {equipmentExpanded ? "Mostrar menos" : `Ver los ${section.equipment.length - VISIBLE_EQUIPMENT_PREVIEW} equipos restantes`}
                              </Button>
                            )}
                          </div>
                          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                            <Input
                              placeholder="Nuevo equipo para esta sección"
                              value={newEquipmentDrafts[draftKey] || ""}
                              onChange={(event) => setNewEquipmentDrafts((current) => ({ ...current, [draftKey]: event.target.value }))}
                              onKeyDown={(event) => { if (event.key === "Enter") void createEquipmentForSection(plantArea.id, section.id); }}
                              className="h-9"
                            />
                            <Button size="sm" variant="outline" onClick={() => void createEquipmentForSection(plantArea.id, section.id)} disabled={!newEquipmentDrafts[draftKey]?.trim() || busy === `equipment-create-${draftKey}`}>
                              {busy === `equipment-create-${draftKey}` ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Plus className="mr-1 h-4 w-4" />}Agregar equipo
                            </Button>
                          </div>
                        </div>
                      );
                    })}
                    <div className="grid gap-2 rounded-md border border-dashed p-3 sm:col-span-2 sm:grid-cols-2">
                      <div className="flex gap-2">
                        <Input
                          placeholder="Crear sección en esta área"
                          value={newSectionDrafts[plantArea.id] || ""}
                          onChange={(event) => setNewSectionDrafts((current) => ({ ...current, [plantArea.id]: event.target.value }))}
                          onKeyDown={(event) => { if (event.key === "Enter") void createSectionForPlantArea(plantArea.id); }}
                          className="h-9"
                        />
                        <Button size="sm" onClick={() => void createSectionForPlantArea(plantArea.id)} disabled={!newSectionDrafts[plantArea.id]?.trim() || busy === `section-create-${plantArea.id}`}>
                          {busy === `section-create-${plantArea.id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}<span className="sr-only">Crear sección</span>
                        </Button>
                      </div>
                      <div className="flex gap-2">
                        <select
                          className="h-9 min-w-0 flex-1 rounded-md border bg-background px-2 text-sm"
                          value={sectionLinkDrafts[plantArea.id] || ""}
                          onChange={(event) => setSectionLinkDrafts((current) => ({ ...current, [plantArea.id]: event.target.value }))}
                          aria-label={`Vincular sección existente a ${plantArea.name}`}
                        >
                          <option value="">{sectionsLinkableToArea(plantArea).length ? "Vincular sección sin área asignada..." : "No hay secciones disponibles para esta área"}</option>
                          {sectionsLinkableToArea(plantArea).map((section) => <option key={section.id} value={section.id}>{section.name}</option>)}
                        </select>
                        <Button size="sm" variant="outline" onClick={() => void linkExistingSection(plantArea.id)} disabled={!sectionLinkDrafts[plantArea.id] || busy === `section-link-${plantArea.id}`}>
                          {busy === `section-link-${plantArea.id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}<span className="sr-only">Vincular sección</span>
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
                {viewingPlantAreaId === plantArea.id && editingPlantAreaId !== plantArea.id && (
                  <div className="border-t pt-2 text-sm sm:col-span-2">
                    {!plantAreaOrders[plantArea.id] ? (
                      <p className="text-muted-foreground">Cargando OTs...</p>
                    ) : plantAreaOrders[plantArea.id].length === 0 ? (
                      <p className="text-muted-foreground">Esta área no tiene OTs relacionadas y se puede eliminar.</p>
                    ) : (
                      <div className="space-y-1">
                        <p className="font-medium">OTs relacionadas: {plantAreaOrders[plantArea.id].length}</p>
                        {plantAreaOrders[plantArea.id].map((order) => (
                          <div key={order.id} className="flex flex-wrap gap-x-2 text-muted-foreground">
                            <span className="font-medium text-foreground">{order.ot_number}</span>
                            <span>{order.title}</span>
                            <span>· {order.status}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mb-4 rounded-lg border bg-card p-4">
        <div className="flex items-start gap-3">
          <FileSpreadsheet className="mt-0.5 h-5 w-5 text-primary" />
          <div className="min-w-0 flex-1">
            <h4 className="font-semibold">Importar inventario con área y sección</h4>
            <p className="mb-3 text-sm text-muted-foreground">
              Usa la hoja Inventario. Se importan las características del equipo y se identifica cada registro por su ID. Las celdas vacías conservan los datos ya guardados. La app revisa IDs repetidos, datos obligatorios y fechas antes de enviar la importación.
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

      <div className="mb-4 rounded-lg border bg-card p-4">
        <div className="mb-2">
          <h4 className="font-semibold">Secciones y equipos pendientes de asignación</h4>
          <p className="text-sm text-muted-foreground">Aquí aparecen las secciones antiguas y los equipos que aún no tienen área. Asigna cada equipo a su área y sección; las secciones con el mismo nombre quedarán separadas por área.</p>
        </div>
        <label className="relative mb-3 block max-w-xl">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            value={sectionSearch}
            onChange={(event) => setSectionSearch(event.target.value)}
            placeholder="Buscar sección o equipo..."
            className="pl-9"
            aria-label="Buscar sección o equipo"
          />
        </label>
        <div className="flex gap-2">
          <Input
            placeholder="Nombre de la sección (ej: Remojo)"
            value={newArea}
            onChange={(event) => {
              setNewArea(event.target.value);
              setAreaMessage("");
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") void addArea();
            }}
            className="h-10"
            disabled={busy === "create-area"}
            aria-label="Nombre de la sección"
          />
          <Button size="sm" onClick={() => void addArea()} disabled={!newArea.trim() || busy === "create-area"}>
            {busy === "create-area" ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Plus className="mr-1 h-4 w-4" />}
            {busy === "create-area" ? "Guardando..." : "Agregar sección"}
          </Button>
        </div>
        {areaMessage && <p className="mt-2 text-sm text-emerald-700">{areaMessage}</p>}
      </div>

      <div className="grid gap-2 xl:grid-cols-2">
        {areas.length === 0 ? (
          <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
            Todavía no hay áreas creadas. Agrega la primera arriba.
          </div>
        ) : !filteredSections.length ? (
          <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground xl:col-span-2">
            No hay secciones ni equipos que coincidan con “{sectionSearch}”.
          </div>
        ) : filteredSections.map((area) => (
          <div key={area.id} id={`legacy-section-${area.id}`} className="rounded-lg border bg-card">
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
                  <span className="min-w-0">
                    <span className="block truncate">{area.name}</span>
                    <span className="block truncate text-xs font-normal text-muted-foreground">
                      {area.plant_area_names?.length ? area.plant_area_names.join(" / ") : "Sin área general asignada"}
                    </span>
                  </span>
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
              <div className="border-t p-3">
                {(() => {
                  const sectionNameMatches = !normalizedSectionSearch || normalizeCatalogSearch(area.name).includes(normalizedSectionSearch);
                  const visibleEquipment = sectionNameMatches
                    ? area.equipment
                    : area.equipment.filter((equipment) => normalizeCatalogSearch(`${equipment.name} ${equipment.inventory_code || ""}`).includes(normalizedSectionSearch));
                  return <>
                <div className="max-h-56 space-y-1 overflow-y-auto pr-1">
                  {visibleEquipment.length === 0 ? (
                    <p className="px-2 py-1 text-sm text-muted-foreground">Sin tipos de equipo todavía.</p>
                  ) : visibleEquipment.map((equipment) => (
                    <div key={equipment.id} id={`legacy-equipment-${equipment.id}`} className="rounded px-2 py-2 text-sm">
                      {editingEquipmentId === equipment.id ? (
                        <div className="flex items-center gap-1">
                          <Input value={equipmentDraft} onChange={(event) => setEquipmentDraft(event.target.value)} className="h-8 flex-1" />
                          <Button size="icon" variant="ghost" onClick={() => saveEquipment(equipment.id)} disabled={busy === `equipment-${equipment.id}`} aria-label="Guardar equipo">
                            {busy === `equipment-${equipment.id}` ? <Loader2 className="animate-spin" /> : <Check />}
                          </Button>
                          <Button size="icon" variant="ghost" onClick={() => setEditingEquipmentId(null)} aria-label="Cancelar edición"><X /></Button>
                        </div>
                      ) : (
                        <>
                          <div className="flex items-center gap-1">
                            <span className="flex-1">{equipment.name}{equipment.inventory_code ? ` — ID ${equipment.inventory_code}` : ""}</span>
                            <Button size="icon" variant="ghost" onClick={() => startEquipmentEdit(equipment)} aria-label="Editar tipo de equipo"><Pencil /></Button>
                            <Button size="icon" variant="ghost" onClick={() => removeEquipment(equipment)} disabled={busy === `delete-equipment-${equipment.id}`} aria-label="Eliminar tipo de equipo">
                              {busy === `delete-equipment-${equipment.id}` ? <Loader2 className="animate-spin" /> : <Trash2 />}
                            </Button>
                          </div>
                          {equipment.plant_area_id == null && <div className="mt-2 grid gap-2 border-t pt-2 sm:grid-cols-[1fr_1fr_auto]">
                            <select
                              className="h-9 min-w-0 rounded-md border bg-background px-2 text-sm"
                              value={(equipmentLocationDrafts[equipment.id] || { plantAreaId: "", sectionId: String(area.id) }).plantAreaId}
                              onChange={(event) => {
                                const plantAreaId = event.target.value;
                                const targetArea = plantAreas.find((item) => String(item.id) === plantAreaId);
                                const currentSectionAvailable = targetArea?.sections.some((item) => item.id === area.id) ?? false;
                                setEquipmentLocationDrafts((current) => ({
                                  ...current,
                                  [equipment.id]: { plantAreaId, sectionId: currentSectionAvailable ? String(area.id) : "" },
                                }));
                              }}
                              aria-label={`Área general de ${equipment.name}`}
                            >
                              <option value="">Asignar a un área...</option>
                              {sortedPlantAreas.map((plantArea) => <option key={plantArea.id} value={plantArea.id}>{plantArea.name}</option>)}
                            </select>
                            <select
                              className="h-9 min-w-0 rounded-md border bg-background px-2 text-sm"
                              value={(equipmentLocationDrafts[equipment.id] || { plantAreaId: "", sectionId: String(area.id) }).sectionId}
                              onChange={(event) => setEquipmentLocationDrafts((current) => ({
                                ...current,
                                [equipment.id]: {
                                  ...(current[equipment.id] || { plantAreaId: "", sectionId: String(area.id) }),
                                  sectionId: event.target.value,
                                },
                              }))}
                              disabled={!(equipmentLocationDrafts[equipment.id]?.plantAreaId)}
                              aria-label={`Sección de ${equipment.name}`}
                            >
                              <option value="">Selecciona sección...</option>
                              {(plantAreas.find((item) => String(item.id) === equipmentLocationDrafts[equipment.id]?.plantAreaId)?.sections || []).map((section) => <option key={section.id} value={section.id}>{section.name}</option>)}
                            </select>
                            <Button size="sm" variant="outline" onClick={() => void assignLegacyEquipment(equipment, area.id)} disabled={!equipmentLocationDrafts[equipment.id]?.plantAreaId || !equipmentLocationDrafts[equipment.id]?.sectionId || busy === `equipment-location-${equipment.id}`}>
                              {busy === `equipment-location-${equipment.id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : "Asignar"}
                            </Button>
                          </div>}
                        </>
                      )}
                    </div>
                  ))}
                </div>
                <div className="flex gap-2 pt-2">
                  <Input placeholder="Tipo de equipo (ej: Filtro)" value={newEquipment} onChange={(event) => setNewEquipment(event.target.value)} className="h-9" />
                  <Button size="sm" variant="outline" onClick={() => addEquipment(area.id)}>Agregar</Button>
                </div>
                  </>;
                })()}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
