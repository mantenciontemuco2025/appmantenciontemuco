"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Loader2, Pencil, Plus, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";
import type { AreaNode, EquipmentNode } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** Admin management for areas and the equipment types under each area. */
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
      fail(err, "Error al crear el área");
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
      fail(err, "Error al editar el área");
    } finally {
      setBusy("");
    }
  }

  async function removeArea(area: AreaNode) {
    if (!window.confirm(`¿Eliminar el área "${area.name}"?`)) return;
    setBusy(`delete-area-${area.id}`);
    setError("");
    try {
      await api.del(`/api/catalogs/areas/${area.id}`);
      if (activeArea === area.id) setActiveArea(null);
      api.invalidateCache("/api/catalogs/tree");
      await load();
    } catch (err) {
      fail(err, "No se pudo eliminar el área");
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

  if (loading) {
    return <div className="flex justify-center py-10"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>;
  }

  return (
    <div>
      <h3 className="mb-1 text-lg font-semibold">Catálogo</h3>
      <p className="mb-4 text-sm text-muted-foreground">Áreas → Tipos de equipo. Puedes crear, editar y eliminar elementos.</p>

      {error && <p className="mb-3 rounded-md bg-destructive/5 p-2 text-sm text-destructive">{error}</p>}

      <div className="mb-4 flex gap-2 rounded-lg border bg-card p-3">
        <Input placeholder="Nueva área (ej: Horno)" value={newArea} onChange={(event) => setNewArea(event.target.value)} className="h-10" />
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
                          <span className="flex-1">{equipment.name}</span>
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
