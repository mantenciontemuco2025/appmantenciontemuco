"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, ArrowLeft, ArrowRight, Check } from "lucide-react";
import { api } from "@/lib/api";
import { formatDuration } from "@/lib/utils";
import type {
  AreaNode,
  MaintenanceDraft,
  MaintenanceRecord,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Card, CardContent } from "@/components/ui/card";
import { VoiceDictation } from "./voice-dictation";
import { cn } from "@/lib/utils";

const STEPS = ["Ubicación", "Trabajo", "Participantes", "Detalles", "Confirmar"] as const;

interface WorkerOption {
  id: number;
  full_name: string;
}

export function MaintenanceWizard() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [loadingCatalog, setLoadingCatalog] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // catalog
  const [areas, setAreas] = useState<AreaNode[]>([]);
  const [workers, setWorkers] = useState<WorkerOption[]>([]);

  // form state — section_name is free text
  const [draft, setDraft] = useState<Partial<MaintenanceDraft>>({
    date: new Date().toISOString().slice(0, 10),
    area_id: null,
    section_name: "",
    equipment_id: null,
    description: "",
    maintenance_type: "PREVENTIVE",
    start_time: "",
    end_time: "",
    participant_ids: [],
  });

  useEffect(() => {
    async function load() {
      try {
        const [tree, users] = await Promise.all([
          api.get<AreaNode[]>("/api/catalogs/tree"),
          api.get<WorkerOption[]>("/api/users/workers"),
        ]);
        setAreas(tree);
        setWorkers(users);
      } catch {
        setWorkers([]);
      } finally {
        setLoadingCatalog(false);
      }
    }
    load();
  }, []);

  const selectedArea = areas.find((a) => a.id === draft.area_id) || null;

  // Equipment filtered by selected area
  const filteredEquipment = selectedArea?.equipment || [];

  const duration = useMemo(() => {
    if (!draft.start_time || !draft.end_time) return null;
    const [sh, sm] = draft.start_time.split(":").map(Number);
    const [eh, em] = draft.end_time.split(":").map(Number);
    const start = sh * 60 + sm;
    const end = eh * 60 + em;
    if (end <= start) return null;
    return end - start;
  }, [draft.start_time, draft.end_time]);

  function set<K extends keyof MaintenanceDraft>(key: K, value: MaintenanceDraft[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
  }

  // Validation per step
  function stepValid(): boolean {
    switch (step) {
      case 0:
        // section_name is free text but must not be empty
        return (
          !!draft.date &&
          !!draft.area_id &&
          !!draft.section_name?.trim() &&
          !!draft.equipment_id
        );
      case 1:
        return !!draft.description && draft.description.trim().length > 0;
      case 2:
        return (draft.participant_ids?.length ?? 0) > 0;
      case 3:
        return (
          !!draft.maintenance_type &&
          !!draft.start_time &&
          !!draft.end_time &&
          duration !== null
        );
      default:
        return true;
    }
  }

  async function submit() {
    if (!draft.date || !draft.area_id || !draft.section_name?.trim() || !draft.equipment_id) return;
    setSubmitting(true);
    setError("");
    try {
      const payload: MaintenanceDraft = {
        date: draft.date,
        area_id: draft.area_id,
        section_name: draft.section_name.trim(),
        equipment_id: draft.equipment_id,
        description: draft.description || "",
        maintenance_type: draft.maintenance_type || "PREVENTIVE",
        start_time: draft.start_time || "",
        end_time: draft.end_time || "",
        participant_ids: draft.participant_ids || [],
      };
      await api.post<MaintenanceRecord>("/api/maintenance", payload);
      router.push("/mantenimientos/historial?created=1");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al registrar la mantención");
    } finally {
      setSubmitting(false);
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
    <div>
      {/* Step indicator */}
      <ol className="mb-6 flex items-center gap-1">
        {STEPS.map((label, i) => (
          <li key={label} className="flex flex-1 items-center">
            <div className="flex flex-col items-center gap-1">
              <span
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold",
                  i === step
                    ? "bg-primary text-primary-foreground"
                    : i < step
                    ? "bg-emerald-500 text-white"
                    : "bg-muted text-muted-foreground"
                )}
              >
                {i < step ? <Check className="h-4 w-4" /> : i + 1}
              </span>
              <span className="text-[10px] text-muted-foreground">{label}</span>
            </div>
            {i < STEPS.length - 1 && (
              <div
                className={cn(
                  "mx-1 h-0.5 flex-1 rounded",
                  i < step ? "bg-emerald-500" : "bg-muted"
                )}
              />
            )}
          </li>
        ))}
      </ol>

      <Card>
        <CardContent className="p-4 space-y-4">
          {step === 0 && (
            <div className="space-y-4">
              <div>
                <label className="text-sm font-medium block mb-1.5">Fecha</label>
                <Input
                  type="date"
                  value={draft.date || ""}
                  onChange={(e) => set("date", e.target.value)}
                />
              </div>
              <Select
                label="Área"
                options={areas.map((a) => ({ value: String(a.id), label: a.name }))}
                value={draft.area_id ? String(draft.area_id) : ""}
                onChange={(e) => {
                  const id = e.target.value ? Number(e.target.value) : null;
                  setDraft((d) => ({ ...d, area_id: id, equipment_id: null }));
                }}
              />
              <div>
                <label className="text-sm font-medium block mb-1.5">Sección</label>
                <Input
                  placeholder="Ej: Horno 3, Línea 2, Sala de bombas..."
                  value={draft.section_name || ""}
                  onChange={(e) => set("section_name", e.target.value)}
                  disabled={!draft.area_id}
                />
                <p className="text-xs text-muted-foreground mt-1">
                  Escriba la sección o ubicación específica del trabajo.
                </p>
              </div>
              <Select
                label="Tipo de equipo"
                options={filteredEquipment.map((eq) => ({
                  value: String(eq.id),
                  label: eq.name,
                }))}
                value={draft.equipment_id ? String(draft.equipment_id) : ""}
                disabled={!draft.area_id}
                onChange={(e) =>
                  set("equipment_id", e.target.value ? Number(e.target.value) : null)
                }
              />
            </div>
          )}

          {step === 1 && (
            <div className="space-y-4">
              <div>
                <label className="text-sm font-medium block mb-1.5">
                  Describe el trabajo realizado
                </label>
                <textarea
                  className="min-h-[160px] w-full rounded-md border border-input bg-background px-3 py-2 text-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  placeholder="Ej: Lubricación de rodamientos y cambio de sello..."
                  value={draft.description || ""}
                  onChange={(e) => set("description", e.target.value)}
                />
              </div>
              <VoiceDictation
                onTranscript={(text) =>
                  setDraft((d) => ({
                    ...d,
                    description: d.description
                      ? `${d.description} ${text}`
                      : text,
                  }))
                }
              />
              <p className="text-xs text-muted-foreground">
                Podrá revisar y editar el texto antes de confirmar.
              </p>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-2">
              <p className="text-sm font-medium">Trabajadores participantes</p>
              {workers.length === 0 && (
                <p className="text-sm text-destructive">
                  No se pudieron cargar los trabajadores. Contacte al administrador.
                </p>
              )}
              {workers.map((w) => {
                const checked = (draft.participant_ids || []).includes(w.id);
                return (
                  <label
                    key={w.id}
                    className="flex items-center gap-3 rounded-md border p-3 cursor-pointer select-none"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() =>
                        set(
                          "participant_ids",
                          checked
                            ? (draft.participant_ids || []).filter((id) => id !== w.id)
                            : [...(draft.participant_ids || []), w.id]
                        )
                      }
                      className="h-5 w-5"
                    />
                    <span className="text-base font-medium">{w.full_name}</span>
                  </label>
                );
              })}
            </div>
          )}

          {step === 3 && (
            <div className="space-y-5">
              <div>
                <p className="text-sm font-medium mb-2">Tipo de mantención</p>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => set("maintenance_type", "PREVENTIVE")}
                    className={cn(
                      "rounded-md border p-4 text-center transition-colors",
                      draft.maintenance_type === "PREVENTIVE"
                        ? "border-primary bg-primary/5 text-primary"
                        : "border-input hover:bg-muted"
                    )}
                  >
                    <div className="text-lg font-semibold">Preventivo</div>
                    <div className="text-xs text-muted-foreground">Programado</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => set("maintenance_type", "CORRECTIVE")}
                    className={cn(
                      "rounded-md border p-4 text-center transition-colors",
                      draft.maintenance_type === "CORRECTIVE"
                        ? "border-destructive bg-destructive/5 text-destructive"
                        : "border-input hover:bg-muted"
                    )}
                  >
                    <div className="text-lg font-semibold">Correctivo</div>
                    <div className="text-xs text-muted-foreground">Reparación</div>
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-sm font-medium block mb-1.5">Hora inicio</label>
                  <Input
                    type="time"
                    value={draft.start_time || ""}
                    onChange={(e) => set("start_time", e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium block mb-1.5">Hora término</label>
                  <Input
                    type="time"
                    value={draft.end_time || ""}
                    onChange={(e) => set("end_time", e.target.value)}
                  />
                </div>
              </div>

              {duration !== null ? (
                <p className="rounded-md bg-muted p-3 text-center text-sm font-medium">
                  Duración: {formatDuration(duration)}
                </p>
              ) : (
                draft.start_time &&
                draft.end_time && (
                  <p className="text-sm text-destructive">
                    La hora de término debe ser posterior a la de inicio.
                  </p>
                )
              )}
            </div>
          )}

          {step === 4 && (
            <div className="space-y-3">
              <h3 className="text-lg font-semibold">Confirme el registro</h3>
              <SummaryRow label="Fecha" value={draft.date || "-"} />
              <SummaryRow label="Área" value={selectedArea?.name || "-"} />
              <SummaryRow label="Sección" value={draft.section_name || "-"} />
              <SummaryRow
                label="Tipo de equipo"
                value={filteredEquipment.find((e) => e.id === draft.equipment_id)?.name || "-"}
              />
              <SummaryRow label="Trabajo" value={draft.description || "-"} />
              <SummaryRow
                label="Participantes"
                value={workers
                  .filter((w) => draft.participant_ids?.includes(w.id))
                  .map((w) => w.full_name)
                  .join(", ")}
              />
              <SummaryRow
                label="Tipo"
                value={draft.maintenance_type === "PREVENTIVE" ? "Preventivo" : "Correctivo"}
              />
              <SummaryRow label="Hora inicio" value={draft.start_time || "-"} />
              <SummaryRow label="Hora término" value={draft.end_time || "-"} />
              <SummaryRow
                label="Duración"
                value={duration !== null ? formatDuration(duration) : "-"}
              />
              {error && (
                <p className="text-sm text-destructive bg-destructive/5 rounded-md p-2">{error}</p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Navigation */}
      <div className="mt-4 flex items-center justify-between gap-3">
        <Button
          variant="outline"
          size="lg"
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          disabled={step === 0 || submitting}
        >
          <ArrowLeft className="mr-1 h-4 w-4" />
          Atrás
        </Button>
        {step < STEPS.length - 1 ? (
          <Button size="lg" onClick={() => setStep((s) => s + 1)} disabled={!stepValid()}>
            Siguiente
            <ArrowRight className="ml-1 h-4 w-4" />
          </Button>
        ) : (
          <Button size="lg" onClick={submit} disabled={submitting}>
            {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Registrar mantención
          </Button>
        )}
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-dashed pb-2 last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-medium text-right">{value}</span>
    </div>
  );
}
