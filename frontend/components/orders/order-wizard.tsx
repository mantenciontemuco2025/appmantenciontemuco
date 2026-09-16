"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Loader2, Plus, Save, Send, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AreaNode, WorkOrderRecord } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Card, CardContent } from "@/components/ui/card";
import { VoiceDictation } from "@/components/maintenance/voice-dictation";
import { todayDateInputValue } from "@/lib/utils";
import { WORK_ORDER_AREAS } from "@/lib/work-order-areas";

interface WorkerOption {
  id: number;
  full_name: string;
}

interface Form {
  scheduled_date: string;
  request_date: string;   // Fecha de solicitud — la coloca el admin al solicitar
  plant_area: string;
  area_id: number | null;
  equipment_id: number | null;
  description: string;
  responsible_user_id: number | null;
  participant_ids: number[];
}

function emptyForm(): Form {
  return {
    scheduled_date: "",
    request_date: todayDateInputValue(),
    plant_area: "",
    area_id: null,
    equipment_id: null,
    description: "",
    responsible_user_id: null,
    participant_ids: [],
  };
}

export function OrderWizard() {
  const router = useRouter();
  const { user } = useAuth();
  const [loadingCatalog, setLoadingCatalog] = useState(true);
  const [submitting, setSubmitting] = useState<"draft" | "emit" | null>(null);
  const [error, setError] = useState("");
  const [draftReady, setDraftReady] = useState(false);
  const [draftRestored, setDraftRestored] = useState(false);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [showNewEquipment, setShowNewEquipment] = useState(false);
  const [newEquipmentName, setNewEquipmentName] = useState("");
  const [creatingEquipment, setCreatingEquipment] = useState(false);
  const [equipmentError, setEquipmentError] = useState("");

  const [areas, setAreas] = useState<AreaNode[]>([]);
  const [workers, setWorkers] = useState<WorkerOption[]>([]);

  const [form, setForm] = useState<Form>(() => emptyForm());

  const draftKey = user ? `mantencion:order-draft:${user.id}` : null;

  useEffect(() => {
    if (!draftKey) return;
    setDraftReady(false);
    try {
      const raw = window.localStorage.getItem(draftKey);
      if (raw) {
        const parsed = JSON.parse(raw) as Partial<Form>;
        setForm((current) => ({ ...current, ...parsed }));
        setDraftRestored(true);
      } else {
        setDraftRestored(false);
      }
    } catch {
      setDraftRestored(false);
    } finally {
      setDraftReady(true);
    }
  }, [draftKey]);

  useEffect(() => {
    if (!draftKey || !draftReady) return;
    const timer = window.setTimeout(() => {
      try {
        window.localStorage.setItem(draftKey, JSON.stringify(form));
        setSavedAt(new Date());
      } catch {
        // El formulario sigue funcionando aunque el navegador no permita almacenamiento.
      }
    }, 500);
    return () => window.clearTimeout(timer);
  }, [draftKey, draftReady, form]);

  function discardLocalDraft() {
    if (draftKey) window.localStorage.removeItem(draftKey);
    setForm(emptyForm());
    setDraftRestored(false);
    setSavedAt(null);
  }

  useEffect(() => {
    async function load() {
      try {
        const [tree, users] = await Promise.all([
          api.getCached<AreaNode[]>("/api/catalogs/tree", 5 * 60 * 1000),
          api.getCached<WorkerOption[]>("/api/users/workers", 60 * 1000),
        ]);
        const supervisorAreaIds =
          user?.role === "SUPERVISOR"
            ? (user.area_ids?.length ? user.area_ids : user.area_id ? [user.area_id] : [])
            : [];
        const visibleAreas =
          user?.role === "SUPERVISOR"
            ? tree.filter((area) => supervisorAreaIds.includes(area.id))
            : tree;
        setAreas(visibleAreas);
        if (user?.role === "SUPERVISOR" && supervisorAreaIds.length) {
          setForm((current) => ({
            ...current,
            area_id: supervisorAreaIds.includes(current.area_id || -1)
              ? current.area_id
              : supervisorAreaIds[0],
          }));
        }
        setWorkers(users);
      } catch {
        setWorkers([]);
      } finally {
        setLoadingCatalog(false);
      }
    }
    load();
  }, [user]);

  const selectedSection = areas.find((a) => a.id === form.area_id) || null;
  const filteredEquipment = selectedSection?.equipment || [];
  const supervisorAreaIds =
    user?.role === "SUPERVISOR"
      ? (user.area_ids?.length ? user.area_ids : user.area_id ? [user.area_id] : [])
      : [];
  const supervisorWithoutArea = user?.role === "SUPERVISOR" && supervisorAreaIds.length === 0;
  const isSupervisor = user?.role === "SUPERVISOR";
  const canCreateEquipment = user?.role === "ADMIN" || isSupervisor;

  function set<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function toggleParticipant(id: number) {
    setForm((f) => ({
      ...f,
      participant_ids: f.participant_ids.includes(id)
        ? f.participant_ids.filter((pid) => pid !== id)
        : [...f.participant_ids, id],
    }));
  }

  async function createEquipment() {
    const name = newEquipmentName.trim();
    if (!name || !form.area_id || creatingEquipment) return;
    setCreatingEquipment(true);
    setEquipmentError("");
    try {
      const created = await api.post<{ id: number; name: string; area_id: number }>(
        "/api/catalogs/equipment",
        { name, area_id: form.area_id }
      );
      setAreas((current) => current.map((area) =>
        area.id === created.area_id
          ? {
              ...area,
              equipment: [...area.equipment, { id: created.id, name: created.name }]
                .sort((a, b) => a.name.localeCompare(b.name, "es")),
            }
          : area
      ));
      api.invalidateCache("/api/catalogs/tree");
      set("equipment_id", created.id);
      setNewEquipmentName("");
      setShowNewEquipment(false);
    } catch (err) {
      setEquipmentError(err instanceof Error ? err.message : "No se pudo guardar el equipo.");
    } finally {
      setCreatingEquipment(false);
    }
  }

  const formValid =
    !!form.request_date &&
    !!form.plant_area &&
    !!form.area_id &&
    !!form.equipment_id &&
    !!form.description.trim() &&
    (isSupervisor || (
      form.responsible_user_id !== null
    ));

  function buildPayload(emit: boolean) {
    return {
      title: (form.description || "").slice(0, 300),
      description: form.description || "",
      plant_area: form.plant_area,
      area_id: form.area_id,
      equipment_id: form.equipment_id,
      maintenance_type: "PREVENTIVE",
      loto_status: "NOT_APPLICABLE",
      request_date: form.request_date || null,
      is_planned: true,
      scheduled_date: form.scheduled_date || form.request_date || null,
      responsible_user_id: isSupervisor ? null : form.responsible_user_id,
      participant_user_ids: isSupervisor ? [] : form.participant_ids,
      emit,
    };
  }

  async function submit(mode: "draft" | "emit") {
    if (!formValid) return;
    setSubmitting(mode);
    setError("");
    try {
      await api.post<WorkOrderRecord>("/api/work-orders", buildPayload(mode === "emit"));
      if (draftKey) window.localStorage.removeItem(draftKey);
      router.push("/ordenes");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al registrar la orden de trabajo");
    } finally {
      setSubmitting(null);
    }
  }

  if (loadingCatalog) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <Card>
      <CardContent className="p-4 space-y-4">
        {/* Fecha de solicitud */}
        <div>
          <label className="text-sm font-medium block mb-1.5">Fecha de solicitud *</label>
          <p className="text-xs text-muted-foreground mb-2">
            Fecha en que se solicita la OT y se incluye en el documento.
          </p>
          <Input
            type="date"
            value={form.request_date || ""}
            onChange={(e) => set("request_date", e.target.value)}
          />
        </div>

        <div className="rounded-lg border border-indigo-200 bg-indigo-50/60 p-3">
          <span className="block text-sm font-semibold text-indigo-950">OT planificada</span>
          <span className="mt-0.5 block text-xs text-indigo-900/80">
            Todas las OTs se consideran planificadas y aparecerán en los KPI de cumplimiento.
          </span>
          <div className="mt-3 border-t border-indigo-200 pt-3">
            <label className="mb-1.5 block text-sm font-medium text-indigo-950">Fecha programada</label>
            <Input
              type="date"
              value={form.scheduled_date}
              onChange={(event) => set("scheduled_date", event.target.value)}
              className="bg-white"
            />
            <p className="mt-1 text-xs text-indigo-900/80">
              Si la dejas vacía, se usará la fecha de solicitud.
            </p>
          </div>
        </div>

        {/* Área general, sección y equipo: el catálogo de sección determina equipos. */}
        <div>
          <h3 className="text-sm font-semibold mb-2">Ubicación del trabajo *</h3>
          <div className="grid grid-cols-1 gap-3">
            <Select
              label="Área"
              options={WORK_ORDER_AREAS.map((name) => ({ value: name, label: name }))}
              value={form.plant_area}
              onChange={(e) => set("plant_area", e.target.value)}
            />
            <SearchableSelect
              label="Sección"
              options={areas.map((a) => ({ value: String(a.id), label: a.name }))}
              value={form.area_id ? String(form.area_id) : ""}
              placeholder="Buscar sección..."
              disabled={supervisorWithoutArea}
              onValueChange={(value) => {
                const id = value ? Number(value) : null;
                setForm((f) => ({ ...f, area_id: id, equipment_id: null }));
                setShowNewEquipment(false);
                setEquipmentError("");
              }}
            />
            <SearchableSelect
              label="Equipo"
              options={filteredEquipment.map((eq) => ({ value: String(eq.id), label: eq.name }))}
              value={form.equipment_id ? String(form.equipment_id) : ""}
              placeholder={form.area_id ? "Buscar equipo..." : "Primero selecciona una sección"}
              emptyMessage="No hay equipos que coincidan con la búsqueda."
              disabled={!form.area_id}
              onValueChange={(value) => set("equipment_id", value ? Number(value) : null)}
            />
            {form.area_id && canCreateEquipment && (
              <div className="-mt-1">
                {!showNewEquipment ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setEquipmentError("");
                      setShowNewEquipment(true);
                    }}
                  >
                    <Plus className="mr-1.5 h-4 w-4" /> No aparece el equipo: agregarlo
                  </Button>
                ) : (
                  <div className="space-y-2 rounded-lg border bg-muted/30 p-3">
                    <label className="block text-sm font-medium" htmlFor="new-equipment-name">
                      Nuevo equipo para {selectedSection?.name}
                    </label>
                    <div className="flex flex-col gap-2 sm:flex-row">
                      <Input
                        id="new-equipment-name"
                        autoFocus
                        maxLength={200}
                        value={newEquipmentName}
                        onChange={(event) => setNewEquipmentName(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault();
                            void createEquipment();
                          }
                        }}
                        placeholder="Nombre del equipo"
                        disabled={creatingEquipment}
                      />
                      <div className="flex gap-2">
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => void createEquipment()}
                          disabled={!newEquipmentName.trim() || creatingEquipment}
                        >
                          {creatingEquipment ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Check className="mr-1 h-4 w-4" />}
                          Guardar
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setShowNewEquipment(false);
                            setNewEquipmentName("");
                            setEquipmentError("");
                          }}
                          disabled={creatingEquipment}
                        >
                          <X className="mr-1 h-4 w-4" /> Cancelar
                        </Button>
                      </div>
                    </div>
                    {equipmentError && <p role="alert" className="text-sm text-destructive">{equipmentError}</p>}
                    <p className="text-xs text-muted-foreground">Se guardará en el catálogo de la sección y quedará seleccionado en esta OT.</p>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Descripción del trabajo */}
        <div>
          <label className="text-sm font-medium block mb-1.5">Descripción del trabajo *</label>
          <textarea
            className="min-h-[100px] w-full rounded-md border border-input bg-background px-3 py-2 text-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            placeholder="Ej: Cambiar sello de la bomba y lubricar rodamientos..."
            value={form.description || ""}
            onChange={(e) => set("description", e.target.value)}
          />
        </div>
        {supervisorWithoutArea && (
          <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            Tu usuario supervisor aún no tiene secciones asignadas. Solicita al administrador configurarlas antes de emitir una OT.
          </p>
        )}
        <VoiceDictation
          onTranscript={(text) =>
            set("description", form.description ? `${form.description} ${text}` : text)
          }
        />
        <div className="flex items-center justify-between gap-3 rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          <span>
            {draftRestored
              ? "Borrador local restaurado."
              : savedAt
                ? `Guardado automáticamente a las ${savedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}.`
                : "Tus avances se guardan automáticamente en este navegador."}
          </span>
          {draftRestored && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={discardLocalDraft}
            >
              <Trash2 className="mr-1 h-3.5 w-3.5" />
              Descartar
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          Podrá revisar y editar el texto antes de guardar.
        </p>

        {/* Solicitado por (firma) — automático: quien emite la OT */}
        <div>
          <label className="text-sm font-medium block mb-1.5">Solicitado por</label>
          <div className="flex items-center gap-2 rounded-lg border bg-muted/40 px-3 py-2">
            <span className="text-sm">{user?.full_name || "—"}</span>
            <span className="ml-auto text-xs text-muted-foreground">Automático</span>
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {isSupervisor
              ? "Se registra con tu nombre; el administrador agregará la firma al aceptar la OT."
              : "Se registra automáticamente con tu nombre y tu firma al emitir la OT."}
          </p>
        </div>

        {/* La asignación la realiza el administrador después de revisar la OT. */}
        {isSupervisor ? (
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
            <p className="font-medium">La asignación la realizará el administrador</p>
            <p className="mt-1 text-xs text-blue-800">
              Envía la solicitud con la información del trabajo. El administrador la revisará,
              elegirá al responsable y agregará los participantes antes de emitirla.
            </p>
          </div>
        ) : (
        <>
        {/* Responsable principal */}
        <div>
          <p className="text-sm font-medium mb-1.5">Responsable principal *</p>
          <p className="text-xs text-muted-foreground mb-2">
            El trabajador que completará el resto de la OT y la ejecutará.
          </p>
          {workers.length === 0 && (
            <p className="text-sm text-destructive">No se pudieron cargar los trabajadores.</p>
          )}
          <Select
            label=""
            options={workers.map((w) => ({ value: String(w.id), label: w.full_name }))}
            value={form.responsible_user_id ? String(form.responsible_user_id) : ""}
            onChange={(e) => {
              const id = e.target.value ? Number(e.target.value) : null;
              setForm((current) => ({
                ...current,
                responsible_user_id: id,
                participant_ids:
                  id !== null && !current.participant_ids.includes(id)
                    ? [...current.participant_ids, id]
                    : current.participant_ids,
              }));
            }}
          />
        </div>

        {/* Participantes (quienes entran a la OT) */}
        <div>
          <p className="text-sm font-medium mb-1.5">Participantes</p>
          <p className="text-xs text-muted-foreground mb-2">
            Quienes entran en esta OT / participan del trabajo. El responsable principal se agrega automáticamente.
          </p>
          {workers.length === 0 && (
            <p className="text-sm text-destructive">No se pudieron cargar los trabajadores.</p>
          )}
          <div className="space-y-1.5">
            {workers.map((w) => {
              const isResponsible = form.responsible_user_id === w.id;
              const checked = isResponsible || form.participant_ids.includes(w.id);
              return (
                <label
                  key={w.id}
                  className="flex items-center gap-3 rounded-md border p-2.5 cursor-pointer select-none"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={isResponsible}
                    onChange={() => toggleParticipant(w.id)}
                    className="h-4 w-4"
                  />
                  <span className="text-sm font-medium">{w.full_name}</span>
                </label>
              );
            })}
          </div>
        </div>
        </>
        )}

        {error && (
          <p className="text-sm text-destructive bg-destructive/5 rounded-md p-2">{error}</p>
        )}

        {/* Actions */}
        <div className="flex gap-2 pt-2">
          <Button
            variant="outline"
            size="lg"
            className="flex-1"
            onClick={() => submit("draft")}
            disabled={submitting !== null || !formValid}
          >
            {submitting === "draft" ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            Guardar Borrador
          </Button>
          <Button
            size="lg"
            className="flex-1"
            onClick={() => submit("emit")}
            disabled={submitting !== null || !formValid}
          >
            {submitting === "emit" ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Send className="mr-2 h-4 w-4" />
            )}
            {isSupervisor ? "Enviar al administrador" : "Emitir OT"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
