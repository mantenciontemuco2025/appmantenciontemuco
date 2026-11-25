"use client";

import { useEffect, useMemo, useState } from "react";
import { Boxes, Combine, Loader2, Pencil, Plus, Save, Search, Trash2, X } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { PageLoading } from "@/components/ui/page-loading";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type CustomAttribute = { label: string; value: string };
type InventoryHierarchy = {
  id: number;
  name: string;
  is_active: boolean;
  sections: { id: number; name: string }[];
};
type EquipmentInventory = {
  id: number; name: string; inventory_code: string | null; area_id: number | null; plant_area_id: number | null; area_name: string | null;
  plant_area_name: string | null; category: string | null; model: string | null;
  dimensions: string | null; weight: string | number | null; unit: string | null;
  description: string | null; location: string | null; purchase_receipt_date: string | null;
  purchased_from: string | null; warranty_end: string | null; web1: string | null;
  initial_value: string | number | null; impeller_diameter: string | null; flow_rate: string | null;
  total_manometric_head: string | null; rotation_speed: string | null; npsh: string | null;
  operational_status: string | null; last_maintenance_date: string | null;
  general_spare_parts: string | null; observations: string | null; power_hp: string | null;
  power_kw: string | null; voltage: string | null; current: string | null;
  revolutions: string | null; efficiency: string | null; capacity: string | null;
  custom_attributes: CustomAttribute[];
  merged_into_equipment_id?: number | null;
};
type EquipmentMergeResult = {
  canonical_equipment_id: number;
  merged_equipment_ids: number[];
  work_orders_moved: number;
  maintenance_records_moved: number;
  preventive_plans_moved: number;
  life_sheet_sync_status: string;
};
type EquipmentMergeHistory = {
  id: number;
  canonical_equipment_id: number;
  canonical_equipment_name: string;
  source_equipment_ids: number[];
  source_equipment_names: string[];
  work_orders_moved: number;
  maintenance_records_moved: number;
  preventive_plans_moved: number;
  status: string;
  life_sheet_sync_status: string;
  created_at: string;
  reverted_at: string | null;
};
type PlantAreaMergeHistory = {
  id: number;
  canonical_plant_area_id: number;
  canonical_plant_area_name: string;
  source_plant_area_ids: number[];
  source_plant_area_names: string[];
  equipment_moved: number;
  sections_moved: number;
  supervisor_assignments_moved: number;
  status: string;
  created_at: string;
  reverted_at: string | null;
};

const fields: { key: keyof EquipmentInventory; label: string; type?: string; multiline?: boolean; adminOnly?: boolean }[] = [
  { key: "category", label: "Categoría" },
  { key: "model", label: "Modelo" },
  { key: "dimensions", label: "Dimensiones" },
  { key: "weight", label: "Peso", type: "number" },
  { key: "unit", label: "Unidad" },
  { key: "description", label: "Descripción", multiline: true },
  { key: "location", label: "Ubicación" },
  { key: "purchase_receipt_date", label: "Fecha compra/recepción", type: "date" },
  { key: "purchased_from", label: "Comprado en / fuente" },
  { key: "warranty_end", label: "Fin garantía", type: "date" },
  { key: "web1", label: "Web / enlace" },
  { key: "initial_value", label: "Valor inicial", type: "number", adminOnly: true },
  { key: "impeller_diameter", label: "Diámetro rodete" },
  { key: "flow_rate", label: "Caudal (Q)" },
  { key: "total_manometric_head", label: "Altura manométrica total (AMT o H)" },
  { key: "rotation_speed", label: "Velocidad de giro (n)" },
  { key: "npsh", label: "NPSH" },
  { key: "operational_status", label: "Estado de operatividad" },
  { key: "general_spare_parts", label: "Repuestos generales", multiline: true },
  { key: "observations", label: "Observaciones", multiline: true },
  { key: "power_hp", label: "Potencia (HP)" },
  { key: "power_kw", label: "Potencia (kW)" },
  { key: "voltage", label: "Voltaje" },
  { key: "current", label: "Corriente" },
  { key: "revolutions", label: "Revoluciones (RPM)" },
  { key: "efficiency", label: "Eficiencia" },
  { key: "capacity", label: "Capacidad" },
];

function dateLabel(value: string | null) {
  if (!value) return "";
  const [year, month, day] = value.slice(0, 10).split("-");
  return `${day}-${month}-${year}`;
}

export default function EquipmentInventoryPage() {
  const { user, loading, logout } = useAuth();
  const [items, setItems] = useState<EquipmentInventory[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<EquipmentInventory | null>(null);
  const [hierarchy, setHierarchy] = useState<InventoryHierarchy[]>([]);
  const [editingLocation, setEditingLocation] = useState(false);
  const [editingCatalogNames, setEditingCatalogNames] = useState(false);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [mergeHistoryOpen, setMergeHistoryOpen] = useState(false);
  const [mergeHistory, setMergeHistory] = useState<EquipmentMergeHistory[]>([]);
  const [mergeSearch, setMergeSearch] = useState("");
  const [mergeSourceIds, setMergeSourceIds] = useState<number[]>([]);
  const [plantAreaMergeOpen, setPlantAreaMergeOpen] = useState(false);
  const [plantAreaMergeHistoryOpen, setPlantAreaMergeHistoryOpen] = useState(false);
  const [plantAreaMergeHistory, setPlantAreaMergeHistory] = useState<PlantAreaMergeHistory[]>([]);
  const [plantAreaCanonicalId, setPlantAreaCanonicalId] = useState("");
  const [plantAreaMergeSearch, setPlantAreaMergeSearch] = useState("");
  const [plantAreaSourceIds, setPlantAreaSourceIds] = useState<number[]>([]);
  const [catalogNameDraft, setCatalogNameDraft] = useState({ equipment_name: "", section_name: "", plant_area_name: "" });
  const [locationAreaId, setLocationAreaId] = useState("");
  const [locationSectionId, setLocationSectionId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ error: boolean; text: string } | null>(null);
  const isAdmin = user?.role === "ADMIN";
  const canEditInventory = isAdmin || (user?.role === "WORKER" && user.can_manage_equipment_inventory);

  async function load() {
    setBusy(true);
    setMessage(null);
    try {
      const rows = await api.get<EquipmentInventory[]>("/api/catalogs/equipment-inventory");
      setItems(rows);
      setSelectedId((current) => current ?? rows[0]?.id ?? null);
    } catch (error) {
      setMessage({ error: true, text: error instanceof Error ? error.message : "No se pudo cargar el inventario." });
    } finally {
      setBusy(false);
    }
  }

  async function loadHierarchy() {
    try {
      const areas = await api.get<InventoryHierarchy[]>("/api/catalogs/hierarchy?include_inactive=true");
      setHierarchy(areas);
    } catch (error) {
      setMessage({ error: true, text: error instanceof Error ? error.message : "No se pudo cargar la jerarquía de áreas y secciones." });
    }
  }

  useEffect(() => {
    if (user) {
      void load();
      if (user.role === "ADMIN" || (user.role === "WORKER" && user.can_manage_equipment_inventory)) void loadHierarchy();
    }
  }, [user]);

  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("es");
    if (!query) return items;
    return items.filter((item) => [item.name, item.inventory_code, item.category, item.model, item.location, item.area_name, item.plant_area_name]
      .some((value) => value?.toLocaleLowerCase("es").includes(query)));
  }, [items, search]);
  const groupedItems = useMemo(() => {
    const areas = new Map<string, { name: string; sections: Map<string, { name: string; items: EquipmentInventory[] }> }>();
    for (const item of filtered) {
      const areaName = item.plant_area_name?.trim() || "SIN ÁREA ASIGNADA";
      const sectionName = item.area_name?.trim() || "SIN SECCIÓN";
      const areaKey = item.plant_area_id == null ? "unassigned" : `area-${item.plant_area_id}`;
      const sectionKey = item.area_id == null ? "unassigned" : `section-${item.area_id}`;
      let area = areas.get(areaKey);
      if (!area) {
        area = { name: areaName, sections: new Map() };
        areas.set(areaKey, area);
      }
      let section = area.sections.get(sectionKey);
      if (!section) {
        section = { name: sectionName, items: [] };
        area.sections.set(sectionKey, section);
      }
      section.items.push(item);
    }
    return [...areas.values()]
      .sort((a, b) => a.name.localeCompare(b.name, "es"))
      .map((area) => ({
        ...area,
        sections: [...area.sections.entries()]
          .sort((a, b) => a[1].name.localeCompare(b[1].name, "es"))
          .map(([id, section]) => ({ ...section, id })),
      }));
  }, [filtered]);
  const selected = items.find((item) => item.id === selectedId) ?? null;
  const mergeCandidates = useMemo(() => {
    const query = mergeSearch.trim().toLocaleLowerCase("es");
    return items.filter((item) => item.id !== selectedId && (!query || [item.name, item.inventory_code, item.area_name, item.plant_area_name]
      .some((value) => value?.toLocaleLowerCase("es").includes(query))));
  }, [items, mergeSearch, selectedId]);
  const plantAreaMergeCandidates = useMemo(() => {
    const query = plantAreaMergeSearch.trim().toLocaleLowerCase("es");
    return hierarchy.filter((area) => area.id !== Number(plantAreaCanonicalId)
      && (!query || area.name.toLocaleLowerCase("es").includes(query)));
  }, [hierarchy, plantAreaCanonicalId, plantAreaMergeSearch]);

  function beginEdit(item: EquipmentInventory) {
    setDraft({ ...item, custom_attributes: item.custom_attributes || [] });
    setEditing(true);
    setMessage(null);
  }

  function beginLocationEdit(item: EquipmentInventory) {
    setLocationAreaId(item.plant_area_id == null ? "" : String(item.plant_area_id));
    setLocationSectionId(item.area_id == null ? "" : String(item.area_id));
    setEditingLocation(true);
    setMessage(null);
  }

  function beginCatalogNamesEdit(item: EquipmentInventory) {
    setCatalogNameDraft({
      equipment_name: item.name,
      section_name: item.area_name || "",
      plant_area_name: item.plant_area_name || "",
    });
    setEditingCatalogNames(true);
    setEditingLocation(false);
    setMessage(null);
  }

  async function saveCatalogNames() {
    if (!selected) return;
    setBusy(true);
    setMessage(null);
    try {
      const payload: Record<string, string> = { equipment_name: catalogNameDraft.equipment_name.trim() };
      if (selected.area_id != null) payload.section_name = catalogNameDraft.section_name.trim();
      if (selected.plant_area_id != null) payload.plant_area_name = catalogNameDraft.plant_area_name.trim();
      const saved = await api.patch<Partial<EquipmentInventory>>(
        `/api/catalogs/equipment/${selected.id}/catalog-names`, payload,
      );
      setItems((current) => current.map((item) => ({
        ...item,
        ...(item.id === selected.id ? { name: saved.name || item.name } : {}),
        ...(saved.area_id != null && item.area_id === saved.area_id ? { area_name: saved.area_name || item.area_name } : {}),
        ...(saved.plant_area_id != null && item.plant_area_id === saved.plant_area_id ? { plant_area_name: saved.plant_area_name || item.plant_area_name } : {}),
      })));
      setEditingCatalogNames(false);
      await loadHierarchy();
      setMessage({ error: false, text: "Nombres actualizados. Las OTs anteriores conservan los nombres con que fueron registradas." });
    } catch (error) {
      setMessage({ error: true, text: error instanceof Error ? error.message : "No se pudieron actualizar los nombres." });
    } finally {
      setBusy(false);
    }
  }

  async function saveLocation() {
    if (!selected || !locationAreaId || !locationSectionId) return;
    setBusy(true);
    setMessage(null);
    try {
      await api.patch(`/api/catalogs/equipment/${selected.id}`, {
        plant_area_id: Number(locationAreaId),
        area_id: Number(locationSectionId),
      });
      setEditingLocation(false);
      const selectedArea = hierarchy.find((area) => area.id === Number(locationAreaId));
      const selectedSection = selectedArea?.sections.find((section) => section.id === Number(locationSectionId));
      if (selectedArea && selectedSection) {
        setItems((current) => current.map((item) => item.id === selected.id
          ? { ...item, plant_area_id: selectedArea.id, plant_area_name: selectedArea.name, area_id: selectedSection.id, area_name: selectedSection.name }
          : item));
      }
      setMessage({ error: false, text: "Área y sección actualizadas. Las OTs históricas se mantienen sin cambios." });
    } catch (error) {
      setMessage({ error: true, text: error instanceof Error ? error.message : "No se pudo actualizar el área y la sección." });
    } finally {
      setBusy(false);
    }
  }

  const locationSections = hierarchy.find((area) => String(area.id) === locationAreaId)?.sections ?? [];

  async function save() {
    if (!draft) return;
    setBusy(true);
    setMessage(null);
    try {
      const saved = await api.patch<EquipmentInventory>(`/api/catalogs/equipment/${draft.id}/inventory`, {
        ...Object.fromEntries(fields
          .filter(({ adminOnly }) => !adminOnly || isAdmin)
          .map(({ key }) => [key, draft[key] === "" ? null : draft[key]])),
        custom_attributes: draft.custom_attributes,
      });
      setItems((current) => current.map((item) => item.id === saved.id ? saved : item));
      setEditing(false);
      setDraft(null);
      setMessage({ error: false, text: "Ficha de inventario guardada." });
    } catch (error) {
      setMessage({ error: true, text: error instanceof Error ? error.message : "No se pudo guardar la ficha." });
    } finally {
      setBusy(false);
    }
  }

  function openMerge() {
    if (!selected) return;
    setMergeSearch(selected.name);
    setMergeSourceIds([]);
    setMergeOpen(true);
    setMessage(null);
  }

  async function mergeSelectedEquipment() {
    if (!selected || mergeSourceIds.length === 0) return;
    const sources = items.filter((item) => mergeSourceIds.includes(item.id));
    const labels = sources.map((item) => `${item.name} (${item.inventory_code || `ID ${item.id}`})`).join(", ");
    if (!window.confirm(`Se unificarán ${sources.length} registro(s) en “${selected.name}”. Las OT, mantenciones y preventivos pasarán al equipo principal; sus folios y fechas se conservarán. ¿Continuar?\n\nDuplicados: ${labels}`)) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.post<EquipmentMergeResult>(`/api/catalogs/equipment/${selected.id}/merge`, { source_equipment_ids: mergeSourceIds });
      setMergeOpen(false);
      setMergeSourceIds([]);
      await load();
      if (mergeHistoryOpen) await loadMergeHistory();
      const syncMessage = result.life_sheet_sync_status === "FAILED"
        ? " La copia de Google Drive no se pudo actualizar; el historial de la app sí quedó unificado."
        : result.life_sheet_sync_status === "PENDING"
          ? " La hoja de vida de Drive queda pendiente de sincronización."
          : " La hoja de vida quedó actualizada.";
      setMessage({ error: result.life_sheet_sync_status === "FAILED", text: `Unificación lista: ${result.work_orders_moved} OT, ${result.maintenance_records_moved} mantenciones y ${result.preventive_plans_moved} preventivos trasladados al equipo principal.${syncMessage}` });
    } catch (error) {
      setMessage({ error: true, text: error instanceof Error ? error.message : "No se pudieron unificar los equipos." });
    } finally {
      setBusy(false);
    }
  }

  async function loadMergeHistory() {
    setBusy(true);
    setMessage(null);
    try {
      setMergeHistory(await api.get<EquipmentMergeHistory[]>("/api/catalogs/equipment-merges"));
    } catch (error) {
      setMessage({ error: true, text: error instanceof Error ? error.message : "No se pudo cargar el historial de unificaciones." });
    } finally {
      setBusy(false);
    }
  }

  async function revertMerge(item: EquipmentMergeHistory) {
    if (!window.confirm(`Se restaurarán los equipos, OT, mantenciones y preventivos tal como estaban antes de esta unificación. La ficha del equipo principal volverá a su estado anterior, por lo que se perderán cambios de inventario hechos después de unirlos. Las actividades nuevas creadas después permanecerán con el equipo principal. ¿Revertir la unión de ${item.source_equipment_names.join(", ")} con ${item.canonical_equipment_name}?`)) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.post<{ merge_id: number; status: string; life_sheet_sync_status: string }>(`/api/catalogs/equipment-merges/${item.id}/revert`, {});
      await load();
      await loadMergeHistory();
      setMessage({ error: result.life_sheet_sync_status === "FAILED", text: result.life_sheet_sync_status === "FAILED"
        ? "La unificación se revirtió en la app, pero Drive no pudo sincronizar las hojas de vida."
        : "Unificación revertida. Se restauraron los vínculos anteriores y se sincronizaron las hojas de vida." });
    } catch (error) {
      setMessage({ error: true, text: error instanceof Error ? error.message : "No se pudo revertir la unificación." });
    } finally {
      setBusy(false);
    }
  }

  async function mergeSelectedPlantAreas() {
    const canonical = hierarchy.find((area) => area.id === Number(plantAreaCanonicalId));
    const sources = hierarchy.filter((area) => plantAreaSourceIds.includes(area.id));
    if (!canonical || !sources.length) return;
    const sourceNames = sources.map((area) => area.name).join(", ");
    if (!window.confirm(`Se unificarán ${sources.length} área(s) en “${canonical.name}”. Los equipos, secciones y permisos de supervisores pasarán al área principal. Las OTs antiguas conservarán sus datos, pero los KPI las agruparán bajo “${canonical.name}”. La unión quedará en el historial y podrá revertirse si después no se cambian sus vínculos.\n\nDuplicadas: ${sourceNames}\n\n¿Continuar?`)) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.post<{ equipment_moved: number; sections_moved: number; supervisor_assignments_moved: number }>(
        `/api/catalogs/plant-areas/${canonical.id}/merge`,
        { source_plant_area_ids: plantAreaSourceIds },
      );
      setPlantAreaMergeOpen(false);
      setPlantAreaSourceIds([]);
      await Promise.all([load(), loadHierarchy()]);
      if (plantAreaMergeHistoryOpen) await loadPlantAreaMergeHistory();
      setMessage({ error: false, text: `Áreas unificadas. ${result.equipment_moved} equipos, ${result.sections_moved} secciones y ${result.supervisor_assignments_moved} permisos de supervisores se trasladaron al área principal. Los KPI agruparán ahí las OTs históricas.` });
    } catch (error) {
      setMessage({ error: true, text: error instanceof Error ? error.message : "No se pudieron unificar las áreas generales." });
    } finally {
      setBusy(false);
    }
  }

  async function loadPlantAreaMergeHistory() {
    setBusy(true);
    setMessage(null);
    try {
      setPlantAreaMergeHistory(await api.get<PlantAreaMergeHistory[]>("/api/catalogs/plant-area-merges"));
    } catch (error) {
      setMessage({ error: true, text: error instanceof Error ? error.message : "No se pudo cargar el historial de áreas." });
    } finally {
      setBusy(false);
    }
  }

  async function revertPlantAreaMerge(item: PlantAreaMergeHistory) {
    if (!window.confirm(`Se restaurarán las áreas “${item.source_plant_area_names.join(", ")}” y sus equipos, secciones y permisos al estado anterior. Los KPI volverán a separar los nombres históricos. Si hubo cambios posteriores en los vínculos, la app bloqueará la reversión para protegerlos. ¿Revertir?`)) return;
    setBusy(true);
    setMessage(null);
    try {
      await api.post<{ merge_id: number; status: string }>(`/api/catalogs/plant-area-merges/${item.id}/revert`, {});
      await Promise.all([load(), loadHierarchy(), loadPlantAreaMergeHistory()]);
      setMessage({ error: false, text: "Unificación de áreas revertida. Se restauraron los equipos, las secciones y los permisos anteriores." });
    } catch (error) {
      setMessage({ error: true, text: error instanceof Error ? error.message : "No se pudo revertir la unificación de áreas." });
    } finally {
      setBusy(false);
    }
  }

  if (loading || !user) return <PageLoading message={loading ? "Validando sesión..." : "Redirigiendo..."} />;

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3"><span className="rounded-xl bg-blue-100 p-3 text-blue-700"><Boxes className="h-6 w-6" /></span><div><h1 className="text-2xl font-bold">Inventario de equipos</h1><p className="mt-1 text-sm text-muted-foreground">Características, ubicación y datos técnicos de los equipos registrados.</p></div></div>
        <div className="flex flex-wrap gap-2">{isAdmin && !editing && <><Button variant="outline" onClick={() => { setPlantAreaCanonicalId(""); setPlantAreaSourceIds([]); setPlantAreaMergeSearch(""); setPlantAreaMergeOpen((open) => !open); }}><Combine className="mr-2 h-4 w-4" />Unificar áreas generales</Button><Button variant="outline" onClick={() => { const opening = !plantAreaMergeHistoryOpen; setPlantAreaMergeHistoryOpen(opening); if (opening) void loadPlantAreaMergeHistory(); }}><Boxes className="mr-2 h-4 w-4" />Historial de áreas</Button></>}{canEditInventory && selected && !editing && <>{isAdmin && <><Button variant="outline" onClick={openMerge}><Combine className="mr-2 h-4 w-4" />Unificar equipos</Button><Button variant="outline" onClick={() => { const opening = !mergeHistoryOpen; setMergeHistoryOpen(opening); if (opening) void loadMergeHistory(); }}><Boxes className="mr-2 h-4 w-4" />Historial de equipos</Button></>}<Button variant="outline" onClick={() => beginCatalogNamesEdit(selected)}><Pencil className="mr-2 h-4 w-4" />Editar nombres</Button><Button onClick={() => beginEdit(selected)}><Pencil className="mr-2 h-4 w-4" />Editar ficha</Button></>}</div>
      </div>

      {message && <div className={`mb-4 rounded-lg border p-3 text-sm ${message.error ? "border-red-200 bg-red-50 text-red-800" : "border-green-200 bg-green-50 text-green-800"}`}>{message.text}</div>}

      {mergeHistoryOpen && isAdmin && <section className="mb-5 rounded-xl border bg-card p-4 shadow-sm sm:p-5"><div className="mb-3 flex items-center justify-between gap-3"><div><h2 className="font-semibold">Historial de unificaciones</h2><p className="text-sm text-muted-foreground">Las uniones activas se pueden revertir desde aquí.</p></div><Button variant="outline" size="sm" onClick={() => void loadMergeHistory()} disabled={busy}><Loader2 className={`mr-2 h-4 w-4 ${busy ? "animate-spin" : "hidden"}`} />Actualizar</Button></div>{mergeHistory.length ? <div className="space-y-2">{mergeHistory.map((item) => <div key={item.id} className="flex flex-wrap items-center gap-3 rounded-lg border p-3"><div className="min-w-64 flex-1"><div className="font-medium">{item.source_equipment_names.join(", ")} → {item.canonical_equipment_name}</div><div className="mt-1 text-xs text-muted-foreground">{dateLabel(item.created_at)} · {item.work_orders_moved} OT · {item.maintenance_records_moved} mantenciones · {item.preventive_plans_moved} preventivos · Drive: {item.life_sheet_sync_status === "SYNCED" ? "sincronizado" : item.life_sheet_sync_status === "FAILED" ? "error" : "pendiente"}</div></div><span className={`rounded-full px-2 py-1 text-xs font-semibold ${item.status === "ACTIVE" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-700"}`}>{item.status === "ACTIVE" ? "Unificada" : "Revertida"}</span>{item.status === "ACTIVE" && <Button variant="outline" size="sm" onClick={() => void revertMerge(item)} disabled={busy}>Revertir</Button>}</div>)}</div> : <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">Todavía no hay unificaciones registradas.</p>}</section>}

      {plantAreaMergeHistoryOpen && isAdmin && <section className="mb-5 rounded-xl border bg-card p-4 shadow-sm sm:p-5"><div className="mb-3 flex items-center justify-between gap-3"><div><h2 className="font-semibold">Historial de unificaciones de áreas</h2><p className="text-sm text-muted-foreground">Puedes revertir una unión mientras no se hayan cambiado sus equipos, secciones o permisos.</p></div><Button variant="outline" size="sm" onClick={() => void loadPlantAreaMergeHistory()} disabled={busy}><Loader2 className={`mr-2 h-4 w-4 ${busy ? "animate-spin" : "hidden"}`} />Actualizar</Button></div>{plantAreaMergeHistory.length ? <div className="space-y-2">{plantAreaMergeHistory.map((item) => <div key={item.id} className="flex flex-wrap items-center gap-3 rounded-lg border p-3"><div className="min-w-64 flex-1"><div className="font-medium">{item.source_plant_area_names.join(", ")} → {item.canonical_plant_area_name}</div><div className="mt-1 text-xs text-muted-foreground">{dateLabel(item.created_at)} · {item.equipment_moved} equipos · {item.sections_moved} secciones · {item.supervisor_assignments_moved} permisos de supervisores · KPI históricos agrupados</div></div><span className={`rounded-full px-2 py-1 text-xs font-semibold ${item.status === "ACTIVE" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-700"}`}>{item.status === "ACTIVE" ? "Unificada" : "Revertida"}</span>{item.status === "ACTIVE" && <Button variant="outline" size="sm" onClick={() => void revertPlantAreaMerge(item)} disabled={busy}>Revertir</Button>}</div>)}</div> : <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">Todavía no hay unificaciones de áreas.</p>}</section>}

      {plantAreaMergeOpen && isAdmin && <section className="mb-5 rounded-xl border border-amber-300 bg-amber-50/50 p-4 shadow-sm sm:p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold">Unificar áreas generales</h2><p className="mt-1 text-sm text-muted-foreground">Elige el área que se conservará y las duplicadas. Se trasladarán sus equipos, secciones y permisos de supervisores; las OTs antiguas mantendrán sus datos y los KPI agruparán sus nombres bajo el área principal.</p></div><Button type="button" variant="ghost" size="icon" aria-label="Cerrar unificación de áreas" onClick={() => setPlantAreaMergeOpen(false)} disabled={busy}><X className="h-4 w-4" /></Button></div><div className="mt-3 grid gap-3 md:grid-cols-2"><label className="text-sm font-medium">Área principal<select className="mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal" value={plantAreaCanonicalId} onChange={(event) => { setPlantAreaCanonicalId(event.target.value); setPlantAreaSourceIds((current) => current.filter((id) => String(id) !== event.target.value)); }}><option value="">Selecciona el área que conservarás</option>{hierarchy.map((area) => <option key={area.id} value={area.id}>{area.name}{area.is_active ? "" : " (Inactiva)"}</option>)}</select></label><label className="text-sm font-medium">Buscar áreas duplicadas<input className="mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal" placeholder="Escribe el nombre del área..." value={plantAreaMergeSearch} onChange={(event) => setPlantAreaMergeSearch(event.target.value)} disabled={!plantAreaCanonicalId} /></label></div><div className="mt-3 max-h-56 space-y-1 overflow-auto rounded-md border bg-background p-2">{plantAreaCanonicalId ? plantAreaMergeCandidates.map((area) => <label key={area.id} className="flex cursor-pointer items-start gap-3 rounded-md p-2 hover:bg-muted/50"><input className="mt-1" type="checkbox" checked={plantAreaSourceIds.includes(area.id)} onChange={(event) => setPlantAreaSourceIds((current) => event.target.checked ? [...current, area.id] : current.filter((id) => id !== area.id))} /><span><span className="block font-medium">{area.name}</span><span className="text-xs text-muted-foreground">{area.sections.length} secciones</span></span></label>) : <p className="p-4 text-center text-sm text-muted-foreground">Selecciona primero el área principal.</p>}{plantAreaCanonicalId && !plantAreaMergeCandidates.length && <p className="p-4 text-center text-sm text-muted-foreground">No hay otras áreas que coincidan con la búsqueda.</p>}</div><div className="mt-3 flex flex-wrap items-center gap-2"><Button onClick={() => void mergeSelectedPlantAreas()} disabled={busy || !plantAreaCanonicalId || !plantAreaSourceIds.length}>{busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Combine className="mr-2 h-4 w-4" />}Unificar {plantAreaSourceIds.length || "áreas"}</Button><Button variant="outline" onClick={() => setPlantAreaMergeOpen(false)} disabled={busy}>Cancelar</Button><span className="text-xs text-muted-foreground">Si después se cambian asignaciones, el sistema bloqueará una reversión que pudiera perder esos cambios.</span></div></section>}

      <div className="grid gap-5 lg:grid-cols-[minmax(240px,0.8fr)_minmax(0,1.6fr)]">
        <section className="rounded-xl border bg-card p-4">
          <div className="relative mb-3"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><input className="h-10 w-full rounded-md border bg-background pl-9 pr-3 text-sm" placeholder="Buscar equipo, código o ubicación..." value={search} onChange={(event) => setSearch(event.target.value)} /></div>
          {busy && !items.length ? <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Cargando equipos...</div> : <div className="max-h-[70vh] space-y-2 overflow-auto">{groupedItems.map((area, areaIndex) => {
            const areaCount = area.sections.reduce((total, section) => total + section.items.length, 0);
            const containsSelection = area.sections.some((section) => section.items.some((item) => item.id === selectedId));
            return <details key={`${area.name}-${areaIndex}`} open={Boolean(search.trim()) || areaIndex === 0 || containsSelection} className="rounded-lg border bg-background">
              <summary className="cursor-pointer list-none px-3 py-3 font-semibold hover:bg-muted/50">{area.name}<span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-xs font-normal text-muted-foreground">{areaCount}</span></summary>
              <div className="space-y-2 border-t p-2">{area.sections.map((section) => <details key={section.id} open={Boolean(search.trim()) || section.items.some((item) => item.id === selectedId)} className="rounded-md bg-muted/30">
                <summary className="cursor-pointer list-none px-3 py-2 text-sm font-medium hover:bg-muted/60">{section.name}<span className="ml-2 text-xs font-normal text-muted-foreground">{section.items.length} equipos</span></summary>
                <div className="space-y-1 px-2 pb-2">{section.items.map((item) => <button type="button" key={item.id} onClick={() => { setSelectedId(item.id); setEditing(false); setDraft(null); setEditingLocation(false); setMessage(null); }} className={`w-full rounded-lg border p-3 text-left hover:border-primary ${selectedId === item.id ? "border-primary bg-primary/5" : "border-transparent bg-background"}`}><div className="font-semibold">{item.name}</div><div className="mt-1 text-xs text-muted-foreground">{item.inventory_code || "Sin código"}{item.category ? ` · ${item.category}` : ""}</div></button>)}</div>
              </details>)}</div>
            </details>;
          })}{!filtered.length && <p className="py-8 text-center text-sm text-muted-foreground">No hay equipos que coincidan.</p>}</div>}
        </section>

        <section className="min-w-0 rounded-xl border bg-card p-4 sm:p-6">
          {!selected ? <div className="py-16 text-center text-sm text-muted-foreground">{items.length ? "Selecciona un equipo para ver su ficha." : "Todavía no hay equipos registrados en el catálogo."}</div> : <>
            <div className="mb-5 flex flex-wrap items-start justify-between gap-3 border-b pb-4"><div><h2 className="text-xl font-semibold">{selected.name}</h2><p className="mt-1 text-sm text-muted-foreground">Código: {selected.inventory_code || "—"} · {selected.area_name || "Sin sección"}{selected.plant_area_name ? ` · ${selected.plant_area_name}` : ""}</p></div><div className="flex flex-wrap gap-2">{isAdmin && !editingLocation && !editing && <Button variant="outline" onClick={() => beginLocationEdit(selected)}><Pencil className="mr-2 h-4 w-4" />Cambiar área/sección</Button>}{editing && <><Button variant="outline" onClick={() => { setEditing(false); setDraft(null); }} disabled={busy}><X className="mr-1 h-4 w-4" />Cancelar</Button><Button onClick={() => void save()} disabled={busy}>{busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}Guardar</Button></>}</div></div>
            {mergeOpen && isAdmin && <div className="mb-5 rounded-lg border border-amber-300 bg-amber-50/60 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-semibold">Unificar equipos en “{selected.name}”</h3><p className="mt-1 text-sm text-muted-foreground">El equipo seleccionado se conservará como principal. El inventario duplicado quedará fuera de las listas y sus OT, mantenciones y preventivos se asociarán al principal. Puedes seleccionar primero coincidencias con el mismo nombre.</p></div><Button type="button" variant="ghost" size="icon" aria-label="Cerrar unificación" onClick={() => setMergeOpen(false)} disabled={busy}><X className="h-4 w-4" /></Button></div>
              <div className="relative mt-3"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><input className="h-10 w-full rounded-md border bg-background pl-9 pr-3 text-sm" placeholder="Buscar duplicado por nombre, código o área..." value={mergeSearch} onChange={(event) => setMergeSearch(event.target.value)} /></div>
              <div className="mt-3 max-h-64 space-y-1 overflow-auto rounded-md border bg-background p-2">{mergeCandidates.map((item) => <label key={item.id} className="flex cursor-pointer items-start gap-3 rounded-md p-2 hover:bg-muted/50"><input className="mt-1" type="checkbox" checked={mergeSourceIds.includes(item.id)} onChange={(event) => setMergeSourceIds((current) => event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} /><span className="min-w-0"><span className="block font-medium">{item.name}</span><span className="text-xs text-muted-foreground">{item.inventory_code || `ID ${item.id}`} · {item.plant_area_name || "Sin área"} → {item.area_name || "Sin sección"}</span></span></label>)}{!mergeCandidates.length && <p className="p-4 text-center text-sm text-muted-foreground">No hay otros equipos que coincidan con la búsqueda.</p>}</div>
              <div className="mt-3 flex flex-wrap items-center gap-2"><Button onClick={() => void mergeSelectedEquipment()} disabled={busy || !mergeSourceIds.length}>{busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Combine className="mr-2 h-4 w-4" />}Unificar {mergeSourceIds.length || "duplicados"}</Button><Button variant="outline" onClick={() => setMergeOpen(false)} disabled={busy}>Cancelar</Button><span className="text-xs text-muted-foreground">Los cambios en los vínculos de historial no se pueden revertir desde la app.</span></div>
            </div>}
            {editingCatalogNames && canEditInventory && <div className="mb-5 rounded-lg border border-blue-200 bg-blue-50/50 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-semibold">Editar nombres del catálogo</h3><p className="mt-1 text-sm text-muted-foreground">Se conservan los vínculos de equipos y secciones. Las OTs anteriores mantienen sus nombres originales.</p></div><Button type="button" variant="ghost" size="icon" aria-label="Cancelar edición de nombres" onClick={() => setEditingCatalogNames(false)} disabled={busy}><X className="h-4 w-4" /></Button></div>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <label className="text-sm font-medium">Equipo<input className="mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal" maxLength={250} value={catalogNameDraft.equipment_name} onChange={(event) => setCatalogNameDraft({ ...catalogNameDraft, equipment_name: event.target.value })} /></label>
                {selected.area_id != null && <label className="text-sm font-medium">Sección<input className="mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal" maxLength={200} value={catalogNameDraft.section_name} onChange={(event) => setCatalogNameDraft({ ...catalogNameDraft, section_name: event.target.value })} /></label>}
                {selected.plant_area_id != null && <label className="text-sm font-medium">Área<input className="mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal" maxLength={100} value={catalogNameDraft.plant_area_name} onChange={(event) => setCatalogNameDraft({ ...catalogNameDraft, plant_area_name: event.target.value })} /></label>}
              </div>
              <div className="mt-3 flex gap-2"><Button onClick={() => void saveCatalogNames()} disabled={busy || !catalogNameDraft.equipment_name.trim() || (selected.area_id != null && !catalogNameDraft.section_name.trim()) || (selected.plant_area_id != null && !catalogNameDraft.plant_area_name.trim())}>{busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}Guardar nombres</Button><Button variant="outline" onClick={() => setEditingCatalogNames(false)} disabled={busy}>Cancelar</Button></div>
            </div>}
            {editingLocation && isAdmin && <div className="mb-5 rounded-lg border border-blue-200 bg-blue-50/50 p-4">
              <h3 className="font-semibold">Asignar equipo a un área y sección</h3>
              <p className="mt-1 text-sm text-muted-foreground">Esto cambia la ubicación del equipo en el catálogo. Las órdenes de trabajo anteriores conservan sus datos.</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <label className="text-sm font-medium">Área general<select className="mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal" value={locationAreaId} onChange={(event) => { setLocationAreaId(event.target.value); setLocationSectionId(""); }}><option value="">Selecciona un área</option>{hierarchy.map((area) => <option key={area.id} value={area.id}>{area.name}{area.is_active ? "" : " (Inactiva)"}</option>)}</select></label>
                <label className="text-sm font-medium">Sección<select className="mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal" value={locationSectionId} onChange={(event) => setLocationSectionId(event.target.value)} disabled={!locationAreaId}><option value="">Selecciona una sección</option>{locationSections.map((section) => <option key={section.id} value={section.id}>{section.name}</option>)}</select></label>
              </div>
              <div className="mt-3 flex gap-2"><Button onClick={() => void saveLocation()} disabled={busy || !locationAreaId || !locationSectionId}>{busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}Guardar ubicación</Button><Button variant="outline" onClick={() => setEditingLocation(false)} disabled={busy}>Cancelar</Button></div>
            </div>}
            {editing && draft ? <div className="space-y-7">
              <div className="rounded-lg border bg-muted/30 px-3 py-2"><div className="text-xs font-medium text-muted-foreground">Fecha última mantención</div><div className="mt-1 text-sm">{dateLabel(selected.last_maintenance_date) || "Sin OT completada asociada"}</div><p className="mt-1 text-xs text-muted-foreground">Se calcula automáticamente desde la OT terminada más reciente y no se edita desde la ficha.</p></div>
              <div className="grid gap-4 sm:grid-cols-2">{fields.filter(({ adminOnly }) => !adminOnly || isAdmin).map(({ key, label, type, multiline }) => <label key={key} className={`block text-sm font-medium ${multiline ? "sm:col-span-2" : ""}`}>{label}{multiline ? <textarea className="mt-1 min-h-24 w-full rounded-md border bg-background px-3 py-2 font-normal" value={String(draft[key] ?? "")} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} /> : <input className="mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal" type={type || "text"} step={type === "number" ? "any" : undefined} value={String(draft[key] ?? "")} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} />}</label>)}</div>
              <div><div className="mb-2 flex flex-wrap items-center justify-between gap-2"><div><h3 className="font-semibold">Características adicionales</h3><p className="text-xs text-muted-foreground">Agrega campos especiales que solo aplican a este equipo.</p></div><Button type="button" variant="outline" size="sm" onClick={() => setDraft({ ...draft, custom_attributes: [...draft.custom_attributes, { label: "", value: "" }] })} disabled={draft.custom_attributes.length >= 50}><Plus className="mr-1 h-4 w-4" />Agregar campo</Button></div><div className="space-y-2">{draft.custom_attributes.map((attribute, index) => <div key={index} className="grid gap-2 sm:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)_40px]"><input className="h-10 rounded-md border bg-background px-3 text-sm" placeholder="Título (ej. Tipo de sello)" value={attribute.label} onChange={(event) => setDraft({ ...draft, custom_attributes: draft.custom_attributes.map((row, i) => i === index ? { ...row, label: event.target.value } : row) })} /><input className="h-10 rounded-md border bg-background px-3 text-sm" placeholder="Valor o texto" value={attribute.value} onChange={(event) => setDraft({ ...draft, custom_attributes: draft.custom_attributes.map((row, i) => i === index ? { ...row, value: event.target.value } : row) })} /><Button type="button" variant="ghost" size="icon" aria-label="Eliminar campo" onClick={() => setDraft({ ...draft, custom_attributes: draft.custom_attributes.filter((_, i) => i !== index) })}><Trash2 className="h-4 w-4 text-red-600" /></Button></div>)}{!draft.custom_attributes.length && <p className="rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground">Aún no hay características adicionales.</p>}</div></div>
            </div> : <>
              <div className="mb-3 rounded-lg bg-muted/40 px-3 py-2"><div className="text-xs font-medium text-muted-foreground">Fecha última mantención</div><div className="mt-1 text-sm">{dateLabel(selected.last_maintenance_date) || "Sin OT completada asociada"}</div></div>
              <div className="grid gap-3 sm:grid-cols-2">{fields.filter(({ adminOnly }) => !adminOnly || isAdmin).map(({ key, label }) => {
                const value = selected[key];
                if (value === null || value === undefined || value === "") return null;
                return <div key={key} className="rounded-lg bg-muted/40 px-3 py-2"><div className="text-xs font-medium text-muted-foreground">{label}</div><div className="mt-1 whitespace-pre-wrap break-words text-sm">{key.toString().includes("date") ? dateLabel(String(value)) : String(value)}</div></div>;
              })}</div>
              {!!selected.custom_attributes?.filter((item) => item.label || item.value).length && <div className="mt-6"><h3 className="mb-2 font-semibold">Características adicionales</h3><div className="grid gap-3 sm:grid-cols-2">{selected.custom_attributes.filter((item) => item.label || item.value).map((item, index) => <div key={`${item.label}-${index}`} className="rounded-lg bg-muted/40 px-3 py-2"><div className="text-xs font-medium text-muted-foreground">{item.label || "Sin título"}</div><div className="mt-1 whitespace-pre-wrap break-words text-sm">{item.value || "—"}</div></div>)}</div></div>}
              {!fields.some(({ key, adminOnly }) => (!adminOnly || isAdmin) && selected[key] !== null && selected[key] !== undefined && selected[key] !== "") && !selected.custom_attributes?.length && <p className="py-8 text-center text-sm text-muted-foreground">Este equipo aún no tiene características de inventario. {canEditInventory ? "Usa “Editar ficha” para completar los datos." : "Un administrador o el trabajador asignado puede completar su ficha."}</p>}
            </>}
          </>}
        </section>
      </div>
    </Shell>
  );
}
