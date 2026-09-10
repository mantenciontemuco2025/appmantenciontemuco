"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { AreaNode, EquipmentNode } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Catalog management (Areas -> Equipment types). Admin-only.
 * Supports adding areas and equipment; deleting (no edit for MVP simplicity).
 * Section is NOT in the catalog — it is free text on each record.
 */

export function CatalogManager() {
  const [areas, setAreas] = useState<AreaNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setAreas(await api.get<AreaNode[]>("/api/catalogs/tree"));
    } catch {
      setAreas([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // New item inputs
  const [newArea, setNewArea] = useState("");
  const [newEquipment, setNewEquipment] = useState("");
  const [activeArea, setActiveArea] = useState<number | null>(null);

  async function addArea() {
    if (!newArea.trim()) return;
    try {
      await api.post("/api/catalogs/areas", { name: newArea.trim() });
      setNewArea("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear área");
    }
  }

  async function addEquipment(areaId: number) {
    if (!newEquipment.trim()) return;
    try {
      await api.post("/api/catalogs/equipment", {
        name: newEquipment.trim(),
        area_id: areaId,
      });
      setNewEquipment("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear equipo");
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-10">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div>
      <h3 className="mb-1 text-lg font-semibold">Catálogo</h3>
      <p className="mb-4 text-sm text-muted-foreground">
        Áreas → Tipos de equipo (la sección se escribe en cada registro)
      </p>

      {error && (
        <p className="mb-3 text-sm text-destructive bg-destructive/5 rounded-md p-2">{error}</p>
      )}

      {/* Add area */}
      <div className="mb-4 flex gap-2 rounded-lg border bg-card p-3">
        <Input
          placeholder="Nueva área (ej: Horno)"
          value={newArea}
          onChange={(e) => setNewArea(e.target.value)}
          className="h-10"
        />
        <Button size="sm" onClick={addArea}>
          <Plus className="mr-1 h-4 w-4" />
          Agregar
        </Button>
      </div>

      <div className="space-y-2">
        {areas.map((area) => (
          <div key={area.id} className="rounded-lg border bg-card">
            <button
              onClick={() => setActiveArea(activeArea === area.id ? null : area.id)}
              className="flex w-full items-center justify-between p-3 text-left font-semibold hover:bg-muted/50"
            >
              <span>{area.name}</span>
              <span className="text-xs text-muted-foreground">
                {area.equipment.length} tipos de equipo
              </span>
            </button>

            {activeArea === area.id && (
              <div className="border-t p-3 space-y-2">
                {/* Lista acotada — si hay muchos equipos, scroll interno en vez
                    de crecer la página infinitamente hacia abajo. */}
                <div className="max-h-56 space-y-1 overflow-y-auto pr-1">
                  {area.equipment.length === 0 ? (
                    <p className="px-2 py-1 text-sm text-muted-foreground">
                      Sin tipos de equipo todavía.
                    </p>
                  ) : (
                    area.equipment.map((eq: EquipmentNode) => (
                      <div
                        key={eq.id}
                        className="flex items-center justify-between rounded px-2 py-1 text-sm"
                      >
                        <span>{eq.name}</span>
                      </div>
                    ))
                  )}
                </div>
                <div className="flex gap-2 pt-2">
                  <Input
                    placeholder="Tipo de equipo (ej: Filtro)"
                    value={newEquipment}
                    onChange={(e) => setNewEquipment(e.target.value)}
                    className="h-9"
                  />
                  <Button size="sm" variant="outline" onClick={() => addEquipment(area.id)}>
                    Agregar
                  </Button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
