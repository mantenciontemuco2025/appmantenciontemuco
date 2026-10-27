"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Plus, X } from "lucide-react";
import { api } from "@/lib/api";
import type { MaterialCatalogItem } from "@/lib/types";
import { Input } from "@/components/ui/input";

type Props = {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
};

function splitCodes(value: string) {
  return Array.from(
    new Set(value.split("-").map((code) => code.trim().toUpperCase()).filter(Boolean)),
  );
}

function mergeMaterials(
  current: MaterialCatalogItem[],
  incoming: MaterialCatalogItem[],
) {
  const merged = new Map(current.map((item) => [item.code, item]));
  let changed = false;
  for (const item of incoming) {
    if (!merged.has(item.code)) {
      merged.set(item.code, item);
      changed = true;
    }
  }
  return changed ? Array.from(merged.values()) : current;
}

/** Catalog-backed multi-select. The OT still stores only CODE-CODE-CODE. */
export function MaterialCodePicker({ value, onChange, disabled = false }: Props) {
  const [materials, setMaterials] = useState<MaterialCatalogItem[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const selectedCodes = useMemo(() => splitCodes(value), [value]);

  useEffect(() => {
    let cancelled = false;
    const normalized = query.trim();
    if (!normalized) {
      setLoading(false);
      setLoadError("");
      return () => { cancelled = true; };
    }

    setLoading(true);
    setLoadError("");
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({ query: normalized, limit: "20" });
      api
        .getCached<MaterialCatalogItem[]>(`/api/materials?${params.toString()}`, 10 * 60 * 1000)
        .then((items) => {
          if (!cancelled) {
            setMaterials((current) => mergeMaterials(current, items));
          }
        })
        .catch(() => {
          if (!cancelled) setLoadError("No se pudo buscar en el catálogo de materiales.");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  // Resolve descriptions for codes already saved on an OT without downloading
  // the full catalog. The API caps this lookup to 50 exact codes.
  useEffect(() => {
    let cancelled = false;
    const missing = selectedCodes.filter((code) => !materials.some((item) => item.code === code));
    if (!missing.length) return () => { cancelled = true; };

    const params = new URLSearchParams();
    params.set("limit", "50");
    for (const code of missing.slice(0, 50)) params.append("codes", code);
    api
      .getCached<MaterialCatalogItem[]>(`/api/materials?${params.toString()}`, 10 * 60 * 1000)
      .then((items) => {
        if (!cancelled) setMaterials((current) => mergeMaterials(current, items));
      })
      .catch(() => {
        if (!cancelled) setLoadError("No se pudieron cargar los nombres de los códigos guardados.");
      });
    return () => { cancelled = true; };
  }, [selectedCodes, materials]);

  const available = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return [];
    return materials
      .filter((material) => !selectedCodes.includes(material.code))
      .filter((material) =>
        `${material.code} ${material.description} ${material.family}`
          .toLowerCase()
          .includes(normalized),
      )
      .slice(0, 12);
  }, [materials, query, selectedCodes]);

  function addCode(code: string) {
    onChange([...selectedCodes, code].join("-"));
    setQuery("");
  }

  function removeCode(code: string) {
    onChange(selectedCodes.filter((current) => current !== code).join("-"));
  }

  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium">Códigos de materiales</label>
      <p className="text-xs text-muted-foreground">
        Busca por código o descripción y selecciona los materiales usados. No se registran cantidades.
      </p>
      <div className="relative">
        <Input
          value={query}
          disabled={disabled}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={loading ? "Cargando catálogo..." : "Ej. B4320001 o abrazadera"}
        />
        {loading && <Loader2 className="absolute right-3 top-2.5 h-4 w-4 animate-spin text-muted-foreground" />}
      </div>
      {available.length > 0 && (
        <div className="max-h-56 overflow-y-auto rounded-md border bg-background shadow-sm">
          {available.map((material) => (
            <button
              type="button"
              key={material.id}
              className="flex w-full items-start gap-2 border-b px-3 py-2 text-left text-sm last:border-0 hover:bg-muted"
              onClick={() => addCode(material.code)}
            >
              <Plus className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <span className="min-w-0">
                <span className="block font-medium">{material.code}</span>
                <span className="block truncate text-xs text-muted-foreground">{material.description}</span>
                <span className="block text-[11px] text-muted-foreground">{material.family}</span>
              </span>
            </button>
          ))}
        </div>
      )}
      {query.trim() && !loading && available.length === 0 && (
        <p className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
          No se encontró un material activo con esa búsqueda. Pídele al administrador que revise el catálogo.
        </p>
      )}
      {loadError && <p className="text-xs text-destructive">{loadError}</p>}
      {selectedCodes.length > 0 && (
        <div className="flex flex-wrap gap-2 rounded-md border bg-muted/30 p-2">
          {selectedCodes.map((code) => {
            const material = materials.find((item) => item.code === code);
            return (
              <span key={code} className="inline-flex max-w-full items-center gap-1 rounded-full border bg-background px-2.5 py-1 text-xs">
                <span className="truncate" title={material?.description || "Código no encontrado en el catálogo"}>
                  {code}{material ? ` — ${material.description}` : " — no encontrado"}
                </span>
                <button type="button" onClick={() => removeCode(code)} disabled={disabled} aria-label={`Quitar ${code}`}>
                  <X className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
                </button>
              </span>
            );
          })}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Se guardará en la OT como: {selectedCodes.length ? selectedCodes.join("-") : "sin códigos"}.
      </p>
    </div>
  );
}
