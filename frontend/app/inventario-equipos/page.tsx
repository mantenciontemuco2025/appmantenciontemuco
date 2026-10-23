"use client";

import { useEffect, useMemo, useState } from "react";
import { Boxes, Loader2, Pencil, Plus, Save, Search, Trash2, X } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { PageLoading } from "@/components/ui/page-loading";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type CustomAttribute = { label: string; value: string };
type EquipmentInventory = {
  id: number; name: string; inventory_code: string | null; area_name: string | null;
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
  { key: "last_maintenance_date", label: "Fecha última mantención", type: "date" },
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

  useEffect(() => { if (user) void load(); }, [user]);

  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("es");
    if (!query) return items;
    return items.filter((item) => [item.name, item.inventory_code, item.category, item.model, item.location, item.area_name, item.plant_area_name]
      .some((value) => value?.toLocaleLowerCase("es").includes(query)));
  }, [items, search]);
  const selected = items.find((item) => item.id === selectedId) ?? null;

  function beginEdit(item: EquipmentInventory) {
    setDraft({ ...item, custom_attributes: item.custom_attributes || [] });
    setEditing(true);
    setMessage(null);
  }

  async function save() {
    if (!draft) return;
    setBusy(true);
    setMessage(null);
    try {
      const saved = await api.patch<EquipmentInventory>(`/api/catalogs/equipment/${draft.id}/inventory`, {
        ...Object.fromEntries(fields.map(({ key }) => [key, draft[key] === "" ? null : draft[key]])),
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

  if (loading || !user) return <PageLoading message={loading ? "Validando sesión..." : "Redirigiendo..."} />;

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3"><span className="rounded-xl bg-blue-100 p-3 text-blue-700"><Boxes className="h-6 w-6" /></span><div><h1 className="text-2xl font-bold">Inventario de equipos</h1><p className="mt-1 text-sm text-muted-foreground">Características, ubicación y datos técnicos de los equipos registrados.</p></div></div>
        {canEditInventory && selected && !editing && <Button onClick={() => beginEdit(selected)}><Pencil className="mr-2 h-4 w-4" />Editar ficha</Button>}
      </div>

      {message && <div className={`mb-4 rounded-lg border p-3 text-sm ${message.error ? "border-red-200 bg-red-50 text-red-800" : "border-green-200 bg-green-50 text-green-800"}`}>{message.text}</div>}

      <div className="grid gap-5 lg:grid-cols-[minmax(240px,0.8fr)_minmax(0,1.6fr)]">
        <section className="rounded-xl border bg-card p-4">
          <div className="relative mb-3"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><input className="h-10 w-full rounded-md border bg-background pl-9 pr-3 text-sm" placeholder="Buscar equipo, código o ubicación..." value={search} onChange={(event) => setSearch(event.target.value)} /></div>
          {busy && !items.length ? <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Cargando equipos...</div> : <div className="max-h-[70vh] space-y-2 overflow-auto">{filtered.map((item) => <button type="button" key={item.id} onClick={() => { setSelectedId(item.id); setEditing(false); setDraft(null); setMessage(null); }} className={`w-full rounded-lg border p-3 text-left hover:border-primary ${selectedId === item.id ? "border-primary bg-primary/5" : ""}`}><div className="font-semibold">{item.name}</div><div className="mt-1 text-xs text-muted-foreground">{item.inventory_code || "Sin código"}{item.category ? ` · ${item.category}` : ""}</div><div className="mt-1 text-xs text-muted-foreground">{item.area_name || "Sin sección"}{item.plant_area_name ? ` · ${item.plant_area_name}` : ""}</div></button>)}{!filtered.length && <p className="py-8 text-center text-sm text-muted-foreground">No hay equipos que coincidan.</p>}</div>}
        </section>

        <section className="min-w-0 rounded-xl border bg-card p-4 sm:p-6">
          {!selected ? <div className="py-16 text-center text-sm text-muted-foreground">{items.length ? "Selecciona un equipo para ver su ficha." : "Todavía no hay equipos registrados en el catálogo."}</div> : <>
            <div className="mb-5 flex flex-wrap items-start justify-between gap-3 border-b pb-4"><div><h2 className="text-xl font-semibold">{selected.name}</h2><p className="mt-1 text-sm text-muted-foreground">Código: {selected.inventory_code || "—"} · {selected.area_name || "Sin sección"}{selected.plant_area_name ? ` · ${selected.plant_area_name}` : ""}</p></div>{editing && <div className="flex gap-2"><Button variant="outline" onClick={() => { setEditing(false); setDraft(null); }} disabled={busy}><X className="mr-1 h-4 w-4" />Cancelar</Button><Button onClick={() => void save()} disabled={busy}>{busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}Guardar</Button></div>}</div>
            {editing && draft ? <div className="space-y-7">
              <div className="grid gap-4 sm:grid-cols-2">{fields.filter(({ adminOnly }) => !adminOnly || isAdmin).map(({ key, label, type, multiline }) => <label key={key} className={`block text-sm font-medium ${multiline ? "sm:col-span-2" : ""}`}>{label}{multiline ? <textarea className="mt-1 min-h-24 w-full rounded-md border bg-background px-3 py-2 font-normal" value={String(draft[key] ?? "")} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} /> : <input className="mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal" type={type || "text"} step={type === "number" ? "any" : undefined} value={String(draft[key] ?? "")} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} />}</label>)}</div>
              <div><div className="mb-2 flex flex-wrap items-center justify-between gap-2"><div><h3 className="font-semibold">Características adicionales</h3><p className="text-xs text-muted-foreground">Agrega campos especiales que solo aplican a este equipo.</p></div><Button type="button" variant="outline" size="sm" onClick={() => setDraft({ ...draft, custom_attributes: [...draft.custom_attributes, { label: "", value: "" }] })} disabled={draft.custom_attributes.length >= 50}><Plus className="mr-1 h-4 w-4" />Agregar campo</Button></div><div className="space-y-2">{draft.custom_attributes.map((attribute, index) => <div key={index} className="grid gap-2 sm:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)_40px]"><input className="h-10 rounded-md border bg-background px-3 text-sm" placeholder="Título (ej. Tipo de sello)" value={attribute.label} onChange={(event) => setDraft({ ...draft, custom_attributes: draft.custom_attributes.map((row, i) => i === index ? { ...row, label: event.target.value } : row) })} /><input className="h-10 rounded-md border bg-background px-3 text-sm" placeholder="Valor o texto" value={attribute.value} onChange={(event) => setDraft({ ...draft, custom_attributes: draft.custom_attributes.map((row, i) => i === index ? { ...row, value: event.target.value } : row) })} /><Button type="button" variant="ghost" size="icon" aria-label="Eliminar campo" onClick={() => setDraft({ ...draft, custom_attributes: draft.custom_attributes.filter((_, i) => i !== index) })}><Trash2 className="h-4 w-4 text-red-600" /></Button></div>)}{!draft.custom_attributes.length && <p className="rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground">Aún no hay características adicionales.</p>}</div></div>
            </div> : <>
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
