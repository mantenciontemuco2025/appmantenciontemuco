"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, Loader2, Pencil, Plus, UserPlus, Users, X } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AreaNode, PlantAreaNode, User, WaterRegisterAccess } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { EmptyState } from "@/components/ui/empty-state";
import { InlineAlert } from "@/components/ui/inline-alert";
import { usePagination } from "@/lib/use-pagination";

const ROLE_OPTIONS = [
  { value: "WORKER", label: "Trabajador" },
  { value: "SUPERVISOR", label: "Supervisor" },
  { value: "ADMIN", label: "Admin" },
];

const PAGE_SIZE = 25;

const WATER_ACCESS_OPTIONS = [
  { value: "NONE", label: "Sin acceso" },
  { value: "VIEW", label: "Solo consulta" },
  { value: "EDIT", label: "Registrar y editar" },
];

type SupervisorScopePickerProps = {
  plantAreas: PlantAreaNode[];
  unassignedSections: AreaNode[];
  plantAreaIds: string[];
  excludedSectionIds: string[];
  legacySectionIds: string[];
  disabled: boolean;
  onTogglePlantArea: (id: number) => void;
  onToggleSectionExclusion: (id: number) => void;
  onToggleLegacySection: (id: number) => void;
};

function SupervisorScopePicker({
  plantAreas, unassignedSections, plantAreaIds, excludedSectionIds, legacySectionIds,
  disabled, onTogglePlantArea, onToggleSectionExclusion, onToggleLegacySection,
}: SupervisorScopePickerProps) {
  const visibleAreas = plantAreas.filter((area) => area.is_active || plantAreaIds.includes(String(area.id)));
  return (
    <div className="space-y-3 rounded-md border p-3">
      <div>
        <p className="text-sm font-medium">Áreas generales asignadas</p>
        <p className="text-xs text-muted-foreground">Al marcar un área, se incluyen sus secciones. Puedes desmarcar secciones específicas.</p>
      </div>
      <div className="max-h-80 space-y-2 overflow-y-auto pr-1">
        {visibleAreas.map((area) => {
          const selected = plantAreaIds.includes(String(area.id));
          const includedCount = area.sections.filter((section) => !excludedSectionIds.includes(String(section.id))).length;
          return (
            <div key={area.id} className="rounded-md bg-muted/30 p-2">
              <label className="flex items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={selected}
                  disabled={disabled || (!area.is_active && !selected)}
                  onChange={() => onTogglePlantArea(area.id)}
                />
                <span className="flex-1">{area.name}{!area.is_active ? " · Inactiva" : ""}</span>
                <span className="text-xs font-normal text-muted-foreground">{selected ? includedCount : 0}/{area.sections.length} secciones</span>
              </label>
              {selected && area.sections.length > 0 && (
                <div className="mt-2 grid gap-x-3 gap-y-1 border-l pl-6 sm:grid-cols-2">
                  {area.sections.map((section) => (
                    <label key={section.id} className="flex items-center gap-2 text-xs">
                      <input
                        type="checkbox"
                        checked={!excludedSectionIds.includes(String(section.id))}
                        disabled={disabled}
                        onChange={() => onToggleSectionExclusion(section.id)}
                      />
                      <span className="truncate" title={section.name}>{section.name}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {!visibleAreas.length && <p className="text-sm text-muted-foreground">No hay áreas generales disponibles.</p>}
      </div>
      {!!unassignedSections.length && (
        <details>
          <summary className="cursor-pointer text-sm font-medium">Secciones sin área general ({legacySectionIds.length} asignadas)</summary>
          <div className="mt-2 grid max-h-40 gap-1 overflow-y-auto rounded-md border p-2 sm:grid-cols-2">
            {unassignedSections.map((section) => (
              <label key={section.id} className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={legacySectionIds.includes(String(section.id))}
                  disabled={disabled}
                  onChange={() => onToggleLegacySection(section.id)}
                />
                <span className="truncate" title={section.name}>{section.name}</span>
              </label>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function waterAccessOf(user: User): WaterRegisterAccess {
  if (user.water_register_access === "NONE") return "NONE";
  if (user.water_register_access === "VIEW" || user.water_register_access === "EDIT") {
    return user.water_register_access;
  }
  if (user.can_manage_water_register || user.role === "SUPERVISOR") return "EDIT";
  return "NONE";
}

function roleLabel(role: string): string {
  return ROLE_OPTIONS.find((r) => r.value === role)?.label || role;
}

export function UserManager() {
  const { user: currentUser } = useAuth();
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  // form
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("WORKER");
  const [waterRegisterAccess, setWaterRegisterAccess] = useState<WaterRegisterAccess>("NONE");
  const [plantAreaIds, setPlantAreaIds] = useState<string[]>([]);
  const [excludedSectionIds, setExcludedSectionIds] = useState<string[]>([]);
  const [legacySectionIds, setLegacySectionIds] = useState<string[]>([]);
  const [areas, setAreas] = useState<AreaNode[]>([]);
  const [plantAreas, setPlantAreas] = useState<PlantAreaNode[]>([]);

  // edit form
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [editFullName, setEditFullName] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [editRole, setEditRole] = useState("WORKER");
  const [editWaterRegisterAccess, setEditWaterRegisterAccess] = useState<WaterRegisterAccess>("NONE");
  const [editInventoryAccess, setEditInventoryAccess] = useState(false);
  const [editPlantAreaIds, setEditPlantAreaIds] = useState<string[]>([]);
  const [editExcludedSectionIds, setEditExcludedSectionIds] = useState<string[]>([]);
  const [editLegacySectionIds, setEditLegacySectionIds] = useState<string[]>([]);
  const [editPassword, setEditPassword] = useState("");
  const [editSaving, setEditSaving] = useState(false);
  const editFormRef = useRef<HTMLFormElement>(null);

  const { items: users, loading, loadingMore, hasMore, error: pageError, loadMore, reload } =
    usePagination<User>({
      fetcher: (_offset, n) => api.get<User[]>(`/api/users?limit=${n}&offset=${_offset}`),
      pageSize: PAGE_SIZE,
    });

  useEffect(() => {
    Promise.all([
      api.getCached<AreaNode[]>("/api/catalogs/tree", 5 * 60 * 1000),
      api.getCached<PlantAreaNode[]>("/api/catalogs/hierarchy?include_inactive=true", 5 * 60 * 1000),
    ]).then(([sectionTree, hierarchy]) => {
      setAreas(sectionTree);
      setPlantAreas(hierarchy);
    }).catch(() => {
      setAreas([]);
      setPlantAreas([]);
    });
  }, []);

  const assignedSectionIds = new Set(plantAreas.flatMap((area) => area.sections.map((section) => section.id)));
  const unassignedSections = areas.filter((section) => !assignedSectionIds.has(section.id));

  const filtered = users.filter((u) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      u.full_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
    );
  });

  // Único admin activo conocido en esta página → su toggle queda bloqueado
  // (el backend también lo impide; aquí lo deshabilitamos antes de intentar).
  const activeAdmins = users.filter((u) => u.role === "ADMIN" && u.is_active);
  const onlyOneActiveAdmin = activeAdmins.length === 1;
  const isOnlyActiveAdmin = (u: User) =>
    u.role === "ADMIN" && u.is_active && onlyOneActiveAdmin;

  useEffect(() => {
    if (pageError) setError(pageError);
  }, [pageError]);

  async function createUser(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      await api.post("/api/users", {
        full_name: fullName,
        email,
        password,
        role,
        water_register_access: waterRegisterAccess,
        area_id: null,
        area_ids: role === "SUPERVISOR" ? legacySectionIds.map(Number) : [],
        plant_area_ids: role === "SUPERVISOR" ? plantAreaIds.map(Number) : [],
        excluded_section_ids: role === "SUPERVISOR" ? excludedSectionIds.map(Number) : [],
      });
      setShowForm(false);
      setFullName("");
      setEmail("");
      setPassword("");
      setRole("WORKER");
      setWaterRegisterAccess("NONE");
      setPlantAreaIds([]);
      setExcludedSectionIds([]);
      setLegacySectionIds([]);
      api.invalidateCache("/api/users/workers");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear usuario");
    } finally {
      setSaving(false);
    }
  }

  async function toggleActive(user: User) {
    try {
      await api.patch(`/api/users/${user.id}`, { is_active: !user.is_active });
      api.invalidateCache("/api/users/workers");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al actualizar usuario");
    }
  }

  function startEdit(user: User) {
    setEditingUser(user);
    setEditFullName(user.full_name);
    setEditEmail(user.email);
    setEditRole(user.role);
    setEditWaterRegisterAccess(waterAccessOf(user));
    setEditInventoryAccess(user.can_manage_equipment_inventory ?? false);
    setEditPlantAreaIds((user.plant_area_ids || []).map(String));
    setEditExcludedSectionIds((user.excluded_section_ids || []).map(String));
    setEditLegacySectionIds((user.legacy_section_ids || []).map(String));
    setEditPassword("");
    setError("");
  }

  useEffect(() => {
    if (!editingUser) return;

    const frame = window.requestAnimationFrame(() => {
      const form = editFormRef.current;
      if (!form) return;
      form.scrollIntoView({ behavior: "smooth", block: "start" });
      form.querySelector<HTMLInputElement>("input:not([type=hidden])")?.focus();
    });

    return () => window.cancelAnimationFrame(frame);
  }, [editingUser]);

  function cancelEdit() {
    setEditingUser(null);
    setEditPassword("");
    setError("");
  }

  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editingUser) return;
    setError("");
    setEditSaving(true);
    try {
      const body: Record<string, unknown> = {
        full_name: editFullName,
        email: editEmail,
        role: editRole,
        water_register_access: editWaterRegisterAccess,
        can_manage_equipment_inventory: editRole === "WORKER" && editInventoryAccess,
        area_id: null,
        area_ids: editRole === "SUPERVISOR" ? editLegacySectionIds.map(Number) : [],
        plant_area_ids: editRole === "SUPERVISOR" ? editPlantAreaIds.map(Number) : [],
        excluded_section_ids: editRole === "SUPERVISOR" ? editExcludedSectionIds.map(Number) : [],
      };
      // Si el admin escribió una nueva contraseña, se envía; si la dejó vacía, no.
      if (editPassword.trim()) body.password = editPassword;
      await api.patch(`/api/users/${editingUser.id}`, body);
      setEditingUser(null);
      setEditPassword("");
      api.invalidateCache("/api/users/workers");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al actualizar usuario");
    } finally {
      setEditSaving(false);
    }
  }

  const activeCount = users.filter((u) => u.is_active).length;

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-2">
        <div>
          <h3 className="text-lg font-semibold">Usuarios</h3>
          <p className="text-xs text-muted-foreground">
            {users.length} en pantalla · {activeCount} activos
          </p>
        </div>
        <Button size="sm" onClick={() => setShowForm((v) => !v)}>
          <UserPlus className="mr-1 h-4 w-4" />
          Nuevo
        </Button>
      </div>

      {error && (
        <InlineAlert variant="error" className="mb-3" onDismiss={() => setError("")}>
          {error}
        </InlineAlert>
      )}

      {showForm && (
        <form onSubmit={createUser} className="mb-4 space-y-3 rounded-lg border bg-card p-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium block">Nombre completo</label>
            <Input value={fullName} onChange={(e) => setFullName(e.target.value)} required />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium block">Email</label>
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium block">Contraseña</label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
            />
          </div>
          <Select
            label="Rol"
            options={ROLE_OPTIONS}
            value={role}
            onChange={(e) => setRole(e.target.value)}
          />
          {role === "SUPERVISOR" && (
            <SupervisorScopePicker
              plantAreas={plantAreas}
              unassignedSections={unassignedSections}
              plantAreaIds={plantAreaIds}
              excludedSectionIds={excludedSectionIds}
              legacySectionIds={legacySectionIds}
              disabled={saving}
              onTogglePlantArea={(id) => {
                const idString = String(id);
                const children = plantAreas.find((area) => area.id === id)?.sections.map((section) => String(section.id)) || [];
                if (plantAreaIds.includes(idString)) {
                  setPlantAreaIds((current) => current.filter((item) => item !== idString));
                  setExcludedSectionIds((current) => current.filter((item) => !children.includes(item)));
                } else {
                  setPlantAreaIds((current) => [...current, idString]);
                  setExcludedSectionIds((current) => current.filter((item) => !children.includes(item)));
                }
              }}
              onToggleSectionExclusion={(id) => setExcludedSectionIds((current) => current.includes(String(id)) ? current.filter((item) => item !== String(id)) : [...current, String(id)])}
              onToggleLegacySection={(id) => setLegacySectionIds((current) => current.includes(String(id)) ? current.filter((item) => item !== String(id)) : [...current, String(id)])}
            />
          )}
          <Select
            label="Permiso de Planta de RILES"
            options={WATER_ACCESS_OPTIONS}
            value={waterRegisterAccess}
            onChange={(e) => setWaterRegisterAccess(e.target.value as WaterRegisterAccess)}
            disabled={saving}
          />
          <Button type="submit" size="lg" className="w-full" disabled={saving || (role === "SUPERVISOR" && !plantAreaIds.length && !legacySectionIds.length)}>
            {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plus className="mr-2 h-4 w-4" />}
            Crear usuario
          </Button>
        </form>
      )}

      {/* Search */}
      <div className="mb-3">
        <Input
          placeholder="Buscar por nombre o email..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Edit form */}
      {editingUser && (
        <form
          ref={editFormRef}
          onSubmit={saveEdit}
          className="mb-4 scroll-mt-24 space-y-3 rounded-lg border border-amber-200 bg-card p-4"
        >
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold">Editar usuario</h4>
            <button
              type="button"
              onClick={cancelEdit}
              disabled={editSaving}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              aria-label="Cancelar edición"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium block">Nombre completo</label>
            <Input
              value={editFullName}
              onChange={(e) => setEditFullName(e.target.value)}
              required
              disabled={editSaving}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium block">Email</label>
            <Input
              type="email"
              value={editEmail}
              onChange={(e) => setEditEmail(e.target.value)}
              required
              disabled={editSaving}
            />
          </div>
          <Select
            label="Rol"
            options={ROLE_OPTIONS}
            value={editRole}
            onChange={(e) => {
              setEditRole(e.target.value);
              if (e.target.value !== "WORKER") setEditInventoryAccess(false);
            }}
            disabled={editSaving}
          />
          {editRole === "SUPERVISOR" && (
            <SupervisorScopePicker
              plantAreas={plantAreas}
              unassignedSections={unassignedSections}
              plantAreaIds={editPlantAreaIds}
              excludedSectionIds={editExcludedSectionIds}
              legacySectionIds={editLegacySectionIds}
              disabled={editSaving}
              onTogglePlantArea={(id) => {
                const idString = String(id);
                const children = plantAreas.find((area) => area.id === id)?.sections.map((section) => String(section.id)) || [];
                if (editPlantAreaIds.includes(idString)) {
                  setEditPlantAreaIds((current) => current.filter((item) => item !== idString));
                  setEditExcludedSectionIds((current) => current.filter((item) => !children.includes(item)));
                } else {
                  setEditPlantAreaIds((current) => [...current, idString]);
                  setEditExcludedSectionIds((current) => current.filter((item) => !children.includes(item)));
                }
              }}
              onToggleSectionExclusion={(id) => setEditExcludedSectionIds((current) => current.includes(String(id)) ? current.filter((item) => item !== String(id)) : [...current, String(id)])}
              onToggleLegacySection={(id) => setEditLegacySectionIds((current) => current.includes(String(id)) ? current.filter((item) => item !== String(id)) : [...current, String(id)])}
            />
          )}
          <Select
            label="Permiso de Planta de RILES"
            options={WATER_ACCESS_OPTIONS}
            value={editWaterRegisterAccess}
            onChange={(e) => setEditWaterRegisterAccess(e.target.value as WaterRegisterAccess)}
            disabled={editSaving}
          />
          {editRole === "WORKER" && (
            <label className="flex items-start gap-2 rounded-md border p-3 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4"
                checked={editInventoryAccess}
                onChange={(event) => setEditInventoryAccess(event.target.checked)}
                disabled={editSaving || !editingUser?.is_active}
              />
              <span>
                <span className="block font-medium">Puede editar el inventario de equipos</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  Solo un trabajador puede tener este permiso. Si se asigna a otra persona, se moverá automáticamente.
                </span>
              </span>
            </label>
          )}
          <div className="space-y-1.5">
            <label className="text-sm font-medium block">
              Restablecer contraseña{" "}
              <span className="font-normal text-muted-foreground">(opcional)</span>
            </label>
            <Input
              type="password"
              value={editPassword}
              onChange={(e) => setEditPassword(e.target.value)}
              placeholder="Dejar vacío para no cambiarla"
              disabled={editSaving}
              minLength={6}
            />
            <p className="text-xs text-muted-foreground">Mínimo 6 caracteres. Si la deja vacía, la contraseña actual se conserva.</p>
          </div>
          <div className="flex gap-2">
            <Button type="submit" size="lg" className="flex-1" disabled={editSaving || (editRole === "SUPERVISOR" && !editPlantAreaIds.length && !editLegacySectionIds.length)}>
              {editSaving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Pencil className="mr-2 h-4 w-4" />}
              Guardar cambios
            </Button>
            <Button type="button" variant="outline" size="lg" className="flex-1" onClick={cancelEdit} disabled={editSaving}>
              <X className="mr-2 h-4 w-4" />
              Cancelar
            </Button>
          </div>
        </form>
      )}

      {loading ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Users className="h-6 w-6" />}
          title="No se encontraron usuarios"
          description={search ? "Pruebe con otro término de búsqueda." : "Cree el primer usuario."}
        />
      ) : (
        <>
          <ul className="space-y-2">
            {filtered.map((u) => {
              const roleBadge =
                u.role === "ADMIN"
                  ? "bg-purple-100 text-purple-700 border-purple-200"
                  : u.role === "SUPERVISOR"
                  ? "bg-blue-100 text-blue-700 border-blue-200"
                  : "bg-slate-100 text-slate-700 border-slate-200";
              return (
                <li key={u.id} className="flex items-center justify-between gap-2 rounded-lg border bg-card p-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{u.full_name}</div>
                    <div className="text-xs text-muted-foreground truncate">{u.email}</div>
                    {u.role === "SUPERVISOR" && (
                      <div className="text-xs text-blue-700">
                        Áreas asignadas: {u.area_names?.length ? u.area_names.join(", ") : "Sin asignar"}
                      </div>
                    )}
                    {u.can_manage_equipment_inventory && (
                      <div className="text-xs font-medium text-emerald-700">Puede editar inventario</div>
                    )}
                  </div>
                  <span className={`hidden sm:inline-flex shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium ${roleBadge}`}>
                    {roleLabel(u.role)}
                  </span>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <button
                      onClick={() => startEdit(u)}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                      title="Editar usuario"
                      aria-label={`Editar a ${u.full_name}`}
                    >
                      <Pencil className="h-4 w-4" />
                    </button>
                    {(currentUser && u.id === currentUser.id) || isOnlyActiveAdmin(u) ? (
                      <span
                        title={
                          currentUser && u.id === currentUser.id
                            ? "No puedes desactivar tu propio usuario"
                            : "Impedido: quedaría sin administradores activos"
                        }
                        className={`cursor-not-allowed rounded-full px-3 py-1 text-xs font-medium border opacity-60 ${
                          u.is_active
                            ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                            : "border-red-200 bg-red-50 text-red-700"
                        }`}
                      >
                        {u.is_active ? "Activo" : "Inactivo"}
                      </span>
                    ) : (
                      <button
                        onClick={() => toggleActive(u)}
                        className={`rounded-full px-3 py-1 text-xs font-medium border transition-colors ${
                          u.is_active
                            ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                            : "border-red-200 bg-red-50 text-red-700"
                        }`}
                      >
                        {u.is_active ? "Activo" : "Inactivo"}
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>

          {/* Footer — contador + Cargar más */}
          <div className="mt-4 flex flex-col items-center gap-3">
            <p className="text-xs text-muted-foreground">
              Mostrando {filtered.length} usuario{filtered.length === 1 ? "" : "s"}
            </p>
            {hasMore && (
              <Button variant="outline" onClick={loadMore} disabled={loadingMore} className="w-full sm:w-auto">
                {loadingMore ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <ChevronDown className="mr-2 h-4 w-4" />
                )}
                Cargar más
              </Button>
            )}
            {!hasMore && users.length > 0 && (
              <p className="text-xs text-muted-foreground">Fin de la lista</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
