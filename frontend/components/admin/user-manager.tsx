"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, Loader2, Pencil, Plus, UserPlus, Users, X } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AreaNode, User } from "@/lib/types";
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
  const [canManageWaterRegister, setCanManageWaterRegister] = useState(false);
  const [areaId, setAreaId] = useState("");
  const [areaIds, setAreaIds] = useState<string[]>([]);
  const [areas, setAreas] = useState<AreaNode[]>([]);

  // edit form
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [editFullName, setEditFullName] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [editRole, setEditRole] = useState("WORKER");
  const [editCanManageWaterRegister, setEditCanManageWaterRegister] = useState(false);
  const [editAreaId, setEditAreaId] = useState("");
  const [editAreaIds, setEditAreaIds] = useState<string[]>([]);
  const [editPassword, setEditPassword] = useState("");
  const [editSaving, setEditSaving] = useState(false);
  const editFormRef = useRef<HTMLFormElement>(null);

  const { items: users, loading, loadingMore, hasMore, error: pageError, loadMore, reload } =
    usePagination<User>({
      fetcher: (_offset, n) => api.get<User[]>(`/api/users?limit=${n}&offset=${_offset}`),
      pageSize: PAGE_SIZE,
    });

  useEffect(() => {
    api.getCached<AreaNode[]>("/api/catalogs/tree", 5 * 60 * 1000).then(setAreas).catch(() => setAreas([]));
  }, []);

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
        can_manage_water_register: canManageWaterRegister,
        area_id: role === "SUPERVISOR" && areaId ? Number(areaId) : null,
        area_ids: role === "SUPERVISOR" ? Array.from(new Set([areaId, ...areaIds].filter(Boolean))).map(Number) : [],
      });
      setShowForm(false);
      setFullName("");
      setEmail("");
      setPassword("");
      setRole("WORKER");
      setCanManageWaterRegister(false);
      setAreaId("");
      setAreaIds([]);
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
    setEditCanManageWaterRegister(user.can_manage_water_register === true);
    setEditAreaId(user.area_id ? String(user.area_id) : "");
    setEditAreaIds((user.area_ids?.length ? user.area_ids : user.area_id ? [user.area_id] : []).map(String));
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
        can_manage_water_register: editCanManageWaterRegister,
        area_id: editRole === "SUPERVISOR" && editAreaId ? Number(editAreaId) : null,
        area_ids: editRole === "SUPERVISOR" ? Array.from(new Set([editAreaId, ...editAreaIds].filter(Boolean))).map(Number) : [],
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
            <>
            <Select
              label="Sección principal supervisada"
              options={areas.map((area) => ({ value: String(area.id), label: area.name }))}
              value={areaId}
              onChange={(e) => {
                setAreaId(e.target.value);
                setAreaIds((current) => e.target.value && !current.includes(e.target.value) ? [e.target.value, ...current] : current);
              }}
              disabled={saving}
              required
            />
            <div className="rounded-md border p-2">
              <p className="mb-1 text-xs font-medium text-muted-foreground">Otras secciones supervisadas</p>
              <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
                {areas.map((area) => (
                  <label key={area.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={areaIds.includes(String(area.id))}
                      onChange={() => setAreaIds((current) => current.includes(String(area.id)) ? current.filter((id) => id !== String(area.id)) : [...current, String(area.id)])}
                    />
                    {area.name}
                  </label>
                ))}
              </div>
            </div>
            </>
          )}
          <label className="flex items-start gap-2 rounded-md border border-cyan-200 bg-cyan-50 p-3 text-sm">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={canManageWaterRegister}
              onChange={(e) => setCanManageWaterRegister(e.target.checked)}
              disabled={saving}
            />
            <span>
              <span className="block font-medium text-cyan-950">Encargado de Registro de agua</span>
              <span className="block text-xs text-cyan-800">Habilita el mÃ³dulo y permite registrar o editar sus datos.</span>
            </span>
          </label>
          <Button type="submit" size="lg" className="w-full" disabled={saving || (role === "SUPERVISOR" && !areaId)}>
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
            onChange={(e) => setEditRole(e.target.value)}
            disabled={editSaving}
          />
          {editRole === "SUPERVISOR" && (
            <>
            <Select
              label="Sección principal supervisada"
              options={areas.map((area) => ({ value: String(area.id), label: area.name }))}
              value={editAreaId}
              onChange={(e) => {
                setEditAreaId(e.target.value);
                setEditAreaIds((current) => e.target.value && !current.includes(e.target.value) ? [e.target.value, ...current] : current);
              }}
              disabled={editSaving}
              required
            />
            <div className="rounded-md border p-2">
              <p className="mb-1 text-xs font-medium text-muted-foreground">Otras secciones supervisadas</p>
              <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
                {areas.map((area) => (
                  <label key={area.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={editAreaIds.includes(String(area.id))}
                      onChange={() => setEditAreaIds((current) => current.includes(String(area.id)) ? current.filter((id) => id !== String(area.id)) : [...current, String(area.id)])}
                    />
                    {area.name}
                  </label>
                ))}
              </div>
            </div>
            </>
          )}
          <label className="flex items-start gap-2 rounded-md border border-cyan-200 bg-cyan-50 p-3 text-sm">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={editCanManageWaterRegister}
              onChange={(e) => setEditCanManageWaterRegister(e.target.checked)}
              disabled={editSaving}
            />
            <span>
              <span className="block font-medium text-cyan-950">Encargado de Registro de agua</span>
              <span className="block text-xs text-cyan-800">Habilita el mÃ³dulo y permite registrar o editar sus datos.</span>
            </span>
          </label>
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
            <Button type="submit" size="lg" className="flex-1" disabled={editSaving || (editRole === "SUPERVISOR" && !editAreaId)}>
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
                        Secciones asignadas: {u.area_names?.length ? u.area_names.join(", ") : "Sin asignar"}
                      </div>
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
