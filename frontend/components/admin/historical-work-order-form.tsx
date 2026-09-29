"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Archive, CheckCircle2, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { AreaNode, User } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { usePlantAreaOptions } from "@/lib/use-plant-area-options";

type FormState = {
  original_ot_number: string;
  title: string;
  description: string;
  plant_area: string;
  area_id: string;
  equipment_id: string;
  maintenance_type: string;
  request_date: string;
  execution_date: string;
  work_time_mode: "MANUAL" | "RANGE";
  duration_hours: string;
  duration_minutes: string;
  work_start_time: string;
  work_end_time: string;
  folio: string;
  voucher_number: string;
  voucher_date: string;
  material_codes: string;
  resources_required: string;
  risks: string;
  observations: string;
  responsible_user_id: string;
  participant_user_ids: string[];
};

const initialForm: FormState = {
  original_ot_number: "", title: "", description: "", plant_area: "", area_id: "",
  equipment_id: "", maintenance_type: "CORRECTIVE", request_date: "", execution_date: "",
  work_time_mode: "MANUAL", duration_hours: "", duration_minutes: "", work_start_time: "", work_end_time: "",
  folio: "", voucher_number: "", voucher_date: "", material_codes: "", resources_required: "",
  risks: "", observations: "", responsible_user_id: "", participant_user_ids: [],
};

export function HistoricalWorkOrderForm() {
  const [form, setForm] = useState<FormState>(initialForm);
  const plantAreaOptions = usePlantAreaOptions();
  const [legacyAreas, setLegacyAreas] = useState<AreaNode[]>([]);
  const [workers, setWorkers] = useState<User[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    void Promise.all([
      api.get<AreaNode[]>("/api/catalogs/tree").then(setLegacyAreas),
      api.get<User[]>("/api/users/workers").then(setWorkers).catch(() => setWorkers([])),
    ]);
  }, []);

  const sections = useMemo(() => legacyAreas, [legacyAreas]);
  const equipment = useMemo(
    () => sections.find((section) => String(section.id) === form.area_id)?.equipment ?? [],
    [form.area_id, sections]
  );

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function selectPlantArea(value: string) {
    setForm((current) => ({ ...current, plant_area: value, area_id: "", equipment_id: "" }));
  }

  function selectSection(value: string) {
    update("area_id", value);
    update("equipment_id", "");
  }

  function toggleParticipant(id: string) {
    setForm((current) => ({
      ...current,
      participant_user_ids: current.participant_user_ids.includes(id)
        ? current.participant_user_ids.filter((item) => item !== id)
        : [...current.participant_user_ids, id],
    }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(""); setNotice(""); setBusy(true);
    try {
      const manualHours = form.duration_hours.trim() === "" ? 0 : Number(form.duration_hours);
      const manualMinutes = form.duration_minutes.trim() === "" ? 0 : Number(form.duration_minutes);
      if (form.work_time_mode === "MANUAL" && (
        manualHours < 0 || manualMinutes < 0 || manualMinutes > 59 ||
        !Number.isInteger(manualHours) || !Number.isInteger(manualMinutes) ||
        (manualHours * 60 + manualMinutes) <= 0
      )) {
        setError("Indica las horas y los minutos trabajados. Los minutos deben estar entre 0 y 59.");
        return;
      }
      const payload: Record<string, unknown> = {
        original_ot_number: form.original_ot_number || null,
        title: form.title,
        description: form.description,
        plant_area: form.plant_area,
        area_id: Number(form.area_id),
        equipment_id: form.equipment_id ? Number(form.equipment_id) : null,
        maintenance_type: form.maintenance_type,
        request_date: form.request_date || null,
        execution_date: form.execution_date,
        work_time_mode: form.work_time_mode,
        worked_duration_minutes: form.work_time_mode === "MANUAL" ? manualHours * 60 + manualMinutes : null,
        work_start_time: form.work_time_mode === "RANGE" ? form.work_start_time : null,
        work_end_time: form.work_time_mode === "RANGE" ? form.work_end_time : null,
        folio: form.folio || null,
        voucher_number: form.voucher_number || null,
        voucher_date: form.voucher_date || null,
        material_codes: form.material_codes || null,
        resources_required: form.resources_required || null,
        risks: form.risks || null,
        observations: form.observations || null,
        responsible_user_id: form.responsible_user_id ? Number(form.responsible_user_id) : null,
        participant_user_ids: form.participant_user_ids.map(Number),
      };
      const created = await api.post<{ ot_number: string; original_ot_number: string | null }>("/api/work-orders/historical", payload);
      setNotice(`OT histórica registrada como ${created.ot_number}${created.original_ot_number ? ` (original ${created.original_ot_number})` : ""}. Ya está incluida en los KPI.`);
      setForm(initialForm);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo registrar la OT histórica.");
    } finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit} className="space-y-5 rounded-xl border bg-card p-5 shadow-sm">
      <div className="flex items-start gap-3">
        <div className="rounded-lg bg-primary/10 p-2 text-primary"><Archive className="h-5 w-5" /></div>
        <div>
          <h2 className="text-lg font-semibold">Registrar OT histórica</h2>
          <p className="text-sm text-muted-foreground">Para trabajos antiguos ya terminados. Se genera un número interno y se conserva el número original.</p>
        </div>
      </div>
      {error && <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}
      {notice && <div className="flex items-center gap-2 rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800"><CheckCircle2 className="h-4 w-4" />{notice}</div>}

      <div className="grid gap-4 md:grid-cols-3">
        <Field label="N.º OT original (opcional)"><Input value={form.original_ot_number} onChange={(e) => update("original_ot_number", e.target.value)} placeholder="Ej. OT-2025-0142" /></Field>
        <Field label="Fecha de solicitud"><Input type="date" value={form.request_date} onChange={(e) => update("request_date", e.target.value)} /></Field>
        <Field label="Fecha de ejecución *"><Input required type="date" value={form.execution_date} onChange={(e) => update("execution_date", e.target.value)} /></Field>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Título del trabajo *"><Input required value={form.title} onChange={(e) => update("title", e.target.value)} /></Field>
        <Field label="Tipo de mantenimiento *"><select className="h-10 w-full rounded-md border bg-background px-3 text-sm" value={form.maintenance_type} onChange={(e) => update("maintenance_type", e.target.value)}><option value="CORRECTIVE">Correctivo</option><option value="PREVENTIVE">Preventivo</option><option value="PREDICTIVE">Predictivo</option><option value="PROYECTO">Proyecto</option><option value="MONTAJE">Montaje</option><option value="URGENTE">Urgente</option></select></Field>
      </div>
      <Field label="Descripción del trabajo realizado *"><textarea required className="min-h-24 w-full rounded-md border bg-background p-3 text-sm" value={form.description} onChange={(e) => update("description", e.target.value)} /></Field>

      <div className="grid gap-4 md:grid-cols-3">
        <Field label="Área de planta *"><select required className="h-10 w-full rounded-md border bg-background px-3 text-sm" value={form.plant_area} onChange={(e) => selectPlantArea(e.target.value)}><option value="">Seleccionar...</option>{plantAreaOptions.map((area) => <option key={area.id} value={area.name}>{area.name}</option>)}</select></Field>
        <Field label="Sección *"><select required className="h-10 w-full rounded-md border bg-background px-3 text-sm" value={form.area_id} onChange={(e) => selectSection(e.target.value)}><option value="">Seleccionar...</option>{sections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
        <Field label="Equipo (opcional)"><select className="h-10 w-full rounded-md border bg-background px-3 text-sm" value={form.equipment_id} onChange={(e) => update("equipment_id", e.target.value)}><option value="">Sin equipo específico</option>{equipment.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
      </div>

      <div className="rounded-lg border p-4">
        <p className="mb-3 text-sm font-medium">Tiempo trabajado *</p>
        <div className="mb-3 flex gap-4 text-sm">
          <label><input type="radio" checked={form.work_time_mode === "MANUAL"} onChange={() => update("work_time_mode", "MANUAL")} /> Duración manual</label>
          <label><input type="radio" checked={form.work_time_mode === "RANGE"} onChange={() => update("work_time_mode", "RANGE")} /> Hora de inicio y término</label>
        </div>
        {form.work_time_mode === "MANUAL" ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Horas trabajadas"><Input min={0} step={1} type="number" value={form.duration_hours} onChange={(e) => update("duration_hours", e.target.value)} placeholder="0" /></Field>
            <Field label="Minutos trabajados"><Input min={0} max={59} step={1} type="number" value={form.duration_minutes} onChange={(e) => update("duration_minutes", e.target.value)} placeholder="0 a 59" /></Field>
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Hora de inicio"><Input required type="time" value={form.work_start_time} onChange={(e) => update("work_start_time", e.target.value)} /></Field>
            <Field label="Hora de término"><Input required type="time" value={form.work_end_time} onChange={(e) => update("work_end_time", e.target.value)} /></Field>
          </div>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-4"><Field label="Folio"><Input value={form.folio} onChange={(e) => update("folio", e.target.value)} /></Field><Field label="N.º de vale"><Input value={form.voucher_number} onChange={(e) => update("voucher_number", e.target.value)} /></Field><Field label="Fecha de vale"><Input type="date" value={form.voucher_date} onChange={(e) => update("voucher_date", e.target.value)} /></Field><Field label="Códigos de materiales"><Input value={form.material_codes} onChange={(e) => update("material_codes", e.target.value)} placeholder="COD-001-COD-002" /></Field></div>

      <div className="grid gap-4 md:grid-cols-3"><Field label="Responsable"><select className="h-10 w-full rounded-md border bg-background px-3 text-sm" value={form.responsible_user_id} onChange={(e) => update("responsible_user_id", e.target.value)}><option value="">Seleccionar...</option>{workers.map((worker) => <option key={worker.id} value={worker.id}>{worker.full_name}</option>)}</select></Field><Field label="Recursos"><textarea className="min-h-20 w-full rounded-md border bg-background p-3 text-sm" value={form.resources_required} onChange={(e) => update("resources_required", e.target.value)} /></Field><Field label="Riesgos"><textarea className="min-h-20 w-full rounded-md border bg-background p-3 text-sm" value={form.risks} onChange={(e) => update("risks", e.target.value)} /></Field></div>
      <Field label="Observaciones"><textarea className="min-h-20 w-full rounded-md border bg-background p-3 text-sm" value={form.observations} onChange={(e) => update("observations", e.target.value)} /></Field>
      <div><p className="mb-2 text-sm font-medium">Participantes (opcional)</p><div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{workers.map((worker) => <label key={worker.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.participant_user_ids.includes(String(worker.id))} onChange={() => toggleParticipant(String(worker.id))} />{worker.full_name}</label>)}</div></div>

      <Button type="submit" disabled={busy}>{busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Archive className="mr-2 h-4 w-4" />}{busy ? "Guardando..." : "Registrar OT histórica"}</Button>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block space-y-1.5 text-sm"><span className="font-medium">{label}</span>{children}</label>;
}
