"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Camera, Check, Loader2, Save, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AreaNode, WorkOrderRecord } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { VoiceDictation } from "@/components/maintenance/voice-dictation";
import { MaterialCodePicker } from "@/components/orders/material-code-picker";
import { WORK_ORDER_AREAS } from "@/lib/work-order-areas";

type HallazgoKind = "COMPLETED" | "REQUIRES_ATTENTION";
type TimeMode = "RANGE" | "MANUAL";
type PendingPhoto = { id: string; file: File; previewUrl: string };

const LOTO_OPTIONS = [
  ["LOTO_BLOQUEO", "LOTO / Bloqueo"],
  ["AST", "AST"],
  ["TARJETA_ROJA", "Tarjeta roja"],
  ["CHECKLIST_HERRAMIENTAS", "Checklist herramientas"],
  ["NOT_APPLICABLE", "No aplica"],
] as const;

function today() {
  return new Date().toISOString().slice(0, 10);
}

function durationLabel(totalMinutes: number) {
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  const parts = [];
  if (hours) parts.push(`${hours} ${hours === 1 ? "hora" : "horas"}`);
  if (minutes || !parts.length) parts.push(`${minutes} ${minutes === 1 ? "minuto" : "minutos"}`);
  return parts.join(" ");
}

function rangeDuration(start: string, end: string) {
  if (!start || !end) return null;
  const [startHour, startMinute] = start.split(":").map(Number);
  const [endHour, endMinute] = end.split(":").map(Number);
  const total = (endHour * 60 + endMinute) - (startHour * 60 + startMinute);
  return total > 0 ? total : null;
}

export function HallazgoWizard() {
  const router = useRouter();
  const { user } = useAuth();
  const [areas, setAreas] = useState<AreaNode[]>([]);
  const [workers, setWorkers] = useState<{ id: number; full_name: string }[]>([]);
  const [plantArea, setPlantArea] = useState<string>(WORK_ORDER_AREAS[0]);
  const [areaId, setAreaId] = useState<number | "">("");
  const [equipmentId, setEquipmentId] = useState<number | "">("");
  const [kind, setKind] = useState<HallazgoKind>("COMPLETED");
  const [timeMode, setTimeMode] = useState<TimeMode>("RANGE");
  const [lotoControls, setLotoControls] = useState<string[]>(["NOT_APPLICABLE"]);
  const [participantIds, setParticipantIds] = useState<number[]>([]);
  const [photos, setPhotos] = useState<PendingPhoto[]>([]);
  const photosRef = useRef<PendingPhoto[]>([]);
  const photoInputRef = useRef<HTMLInputElement | null>(null);
  const [form, setForm] = useState({
    title: "", description: "", maintenance_type: "CORRECTIVE", priority: "NORMAL",
    report_date: today(), folio: "", voucher_number: "", material_codes: "", start: "", end: "", duration_hours: "", duration_minutes: "", resources: "", risks: "", observations: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api.getCached<AreaNode[]>("/api/catalogs/tree", 300000),
      api.getCached<{ id: number; full_name: string }[]>("/api/users/workers", 60000),
    ]).then(([tree, users]) => {
      const visible = user?.role === "SUPERVISOR" && user.area_ids.length
        ? tree.filter((area) => user.area_ids.includes(area.id)) : tree;
      setAreas(visible);
      setWorkers(users);
      if (visible[0]) setAreaId(visible[0].id);
    }).catch(() => setError("No se pudo cargar el catálogo de áreas y equipos."))
      .finally(() => setLoading(false));
  }, [user]);

  useEffect(() => { photosRef.current = photos; }, [photos]);
  useEffect(() => () => photosRef.current.forEach((photo) => URL.revokeObjectURL(photo.previewUrl)), []);

  const selectedArea = useMemo(() => areas.find((area) => area.id === areaId), [areas, areaId]);

  function setField(key: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function appendField(key: keyof typeof form, text: string) {
    setForm((current) => ({
      ...current,
      [key]: current[key] ? `${current[key]} ${text}` : text,
    }));
  }

  function toggleLoto(value: string) {
    setLotoControls((current) => {
      if (value === "NOT_APPLICABLE") return ["NOT_APPLICABLE"];
      const next = current.filter((item) => item !== "NOT_APPLICABLE");
      const updated = next.includes(value) ? next.filter((item) => item !== value) : [...next, value];
      return updated.length ? updated : ["NOT_APPLICABLE"];
    });
  }

  function toggleParticipant(id: number) {
    setParticipantIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function chooseKind(value: HallazgoKind) {
    setKind(value);
    setError("");
  }

  function choosePhotos(files: FileList | null) {
    if (!files?.length) return;
    const available = Math.max(0, 2 - photos.length);
    const selected = Array.from(files).filter((file) => file.type.startsWith("image/")).slice(0, available);
    setPhotos((current) => [...current, ...selected.map((file) => ({
      id: `${Date.now()}-${Math.random()}`,
      file,
      previewUrl: URL.createObjectURL(file),
    }))]);
    if (photoInputRef.current) photoInputRef.current.value = "";
  }

  function removePhoto(id: string) {
    setPhotos((current) => {
      const photo = current.find((item) => item.id === id);
      if (photo) URL.revokeObjectURL(photo.previewUrl);
      return current.filter((item) => item.id !== id);
    });
  }

  async function uploadPhotos(workOrderId: number) {
    for (const photo of photos) {
      const body = new FormData();
      body.append("file", photo.file);
      body.append("stage", "ISSUE");
      await api.upload(`/api/work-orders/${workOrderId}/evidence`, body, 120000);
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    if (!areaId || !form.title.trim() || !form.description.trim()) {
      setError("Completa el título, la descripción y la sección."); return;
    }
    if (kind === "COMPLETED" && timeMode === "RANGE" && (!form.start || !form.end)) {
      setError("Indica la hora de inicio y término."); return;
    }
    const manualHours = form.duration_hours.trim() === "" ? 0 : Number(form.duration_hours);
    const manualMinutes = form.duration_minutes.trim() === "" ? 0 : Number(form.duration_minutes);
    if (kind === "COMPLETED" && timeMode === "MANUAL" && (
      manualHours < 0 || manualMinutes < 0 || manualMinutes > 59 || !Number.isInteger(manualHours) || !Number.isInteger(manualMinutes) || (manualHours * 60 + manualMinutes) <= 0
    )) {
      setError("Indica las horas y los minutos trabajados. Los minutos deben estar entre 0 y 59."); return;
    }
    setSaving(true);
    try {
      const payload = {
        title: form.title.trim(), description: form.description.trim(), area_id: areaId,
        plant_area: plantArea, equipment_id: equipmentId || null,
        report_kind: kind, priority: form.priority, report_date: form.report_date,
        folio: form.folio.trim() || null, voucher_number: form.voucher_number.trim() || null,
        material_codes: form.material_codes.trim() || null,
        risks: form.risks || null, observations: form.observations || null,
        ...(kind === "COMPLETED" ? {
          maintenance_type: form.maintenance_type, loto_controls: lotoControls,
          resources_required: form.resources || null, participant_user_ids: participantIds,
          work_time_mode: timeMode,
          ...(timeMode === "RANGE" ? { work_start_time: form.start, work_end_time: form.end } : { worked_duration_minutes: manualHours * 60 + manualMinutes }),
        } : {}),
      };
      const report = await api.post<WorkOrderRecord>("/api/work-orders/hallazgos", payload);
      if (photos.length) await uploadPhotos(report.id);
      router.push(`/ordenes/${report.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo enviar el hallazgo.");
    } finally { setSaving(false); }
  }

  if (loading) return <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Cargando catálogo...</div>;

  const completed = kind === "COMPLETED";
  return (
    <form onSubmit={submit} className="space-y-5 rounded-xl border bg-card p-5 shadow-sm">
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
        <AlertTriangle className="mr-1 inline h-4 w-4" /> El registro queda como <strong>HALL</strong> y el administrador decidirá si lo convierte en OT.
      </div>
      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700" role="alert">{error}</p>}

      <div className="grid gap-4 md:grid-cols-2">
        <label className="text-sm font-medium">Tipo de registro
          <select className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={kind} onChange={(e) => chooseKind(e.target.value as HallazgoKind)}>
            <option value="COMPLETED">Trabajo ya realizado</option>
            <option value="REQUIRES_ATTENTION">Requiere atención / asignación</option>
          </select>
        </label>
        <label className="text-sm font-medium">Prioridad
          <select className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={form.priority} onChange={(e) => setField("priority", e.target.value)}>
            <option value="NORMAL">Normal</option><option value="URGENT">Urgente</option><option value="EMERGENCY">Emergencia</option>
          </select>
        </label>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div><label className="text-sm font-medium">Título</label><input className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={form.title} onChange={(e) => setField("title", e.target.value)} placeholder="Ej. Fuga detectada en bomba" /><VoiceDictation onTranscript={(text) => appendField("title", text)} /></div>
        <label className="text-sm font-medium">Fecha del hecho<input type="date" className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={form.report_date} onChange={(e) => setField("report_date", e.target.value)} /></label>
      </div>

      <div className="grid gap-4 md:grid-cols-2"><label className="text-sm font-medium">Folio <span className="font-normal text-muted-foreground">(opcional)</span><input className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={form.folio} onChange={(e) => setField("folio", e.target.value)} placeholder="Folio de la OT" /></label><label className="text-sm font-medium">N.º de vale <span className="font-normal text-muted-foreground">(opcional)</span><input className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={form.voucher_number} onChange={(e) => setField("voucher_number", e.target.value)} placeholder="Número de vale" /></label></div>

      <div className="grid gap-4 md:grid-cols-2">
        <label className="text-sm font-medium">Área de planta<select className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={plantArea} onChange={(e) => setPlantArea(e.target.value)}>{WORK_ORDER_AREAS.map((area) => <option key={area} value={area}>{area}</option>)}</select></label>
        <label className="text-sm font-medium">Sección<select className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={areaId} onChange={(e) => { setAreaId(Number(e.target.value)); setEquipmentId(""); }}>{areas.map((area) => <option key={area.id} value={area.id}>{area.name}</option>)}</select></label>
      </div>
      <label className="block text-sm font-medium">Equipo (opcional)<select className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={equipmentId} onChange={(e) => setEquipmentId(e.target.value ? Number(e.target.value) : "")}><option value="">Sin equipo específico / agregar después</option>{(selectedArea?.equipment || []).map((equipment) => <option key={equipment.id} value={equipment.id}>{equipment.name}</option>)}</select></label>

      <div><label className="block text-sm font-medium">Descripción detallada</label><textarea className="mt-1 min-h-28 w-full rounded-md border bg-background px-3 py-2" value={form.description} onChange={(e) => setField("description", e.target.value)} placeholder={completed ? "Describe el trabajo realizado..." : "Describe el problema o trabajo que debe realizarse..."} /><VoiceDictation onTranscript={(text) => appendField("description", text)} /></div>

      {completed && <>
        <div className="grid gap-4 md:grid-cols-2"><label className="text-sm font-medium">Tipo de mantenimiento<select className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={form.maintenance_type} onChange={(e) => setField("maintenance_type", e.target.value)}><option value="PREVENTIVE">Preventivo</option><option value="CORRECTIVE">Correctivo</option><option value="PREDICTIVE">Predictivo</option><option value="PROYECTO">Proyecto</option><option value="MONTAJE">Montaje</option><option value="URGENTE">Urgente</option></select></label><div className="text-sm"><span className="font-medium">Tiempo trabajado</span><div className="mt-2 flex gap-4"><label><input type="radio" checked={timeMode === "RANGE"} onChange={() => setTimeMode("RANGE")} /> Desde / hasta</label><label><input type="radio" checked={timeMode === "MANUAL"} onChange={() => setTimeMode("MANUAL")} /> Manual</label></div></div></div>
        {timeMode === "RANGE" ? <div className="grid gap-3 md:grid-cols-2"><label className="text-sm">Hora de inicio<input type="time" className="mt-1 w-full rounded-md border px-3 py-2" value={form.start} onChange={(e) => setField("start", e.target.value)} /></label><label className="text-sm">Hora de término<input type="time" className="mt-1 w-full rounded-md border px-3 py-2" value={form.end} onChange={(e) => setField("end", e.target.value)} /></label>{rangeDuration(form.start, form.end) !== null && <p className="text-sm text-muted-foreground md:col-span-2">Duración calculada: <strong>{durationLabel(rangeDuration(form.start, form.end) || 0)}</strong></p>}</div> : <div><span className="block text-sm font-medium">Duración manual</span><div className="mt-1 grid gap-3 sm:grid-cols-2"><label className="text-sm">Horas<input type="number" min="0" step="1" className="mt-1 w-full rounded-md border px-3 py-2" value={form.duration_hours} onChange={(e) => setField("duration_hours", e.target.value)} placeholder="0" /></label><label className="text-sm">Minutos<input type="number" min="0" max="59" step="1" className="mt-1 w-full rounded-md border px-3 py-2" value={form.duration_minutes} onChange={(e) => setField("duration_minutes", e.target.value)} placeholder="0 a 59" /></label></div></div>}
        <div className="rounded-lg border p-4"><span className="mb-2 block text-sm font-medium">LOTO / Bloqueo / AST</span><div className="grid gap-2 sm:grid-cols-2">{LOTO_OPTIONS.map(([value, label]) => <label key={value} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={lotoControls.includes(value)} onChange={() => toggleLoto(value)} />{lotoControls.includes(value) && <Check className="h-3 w-3 text-primary" />}{label}</label>)}</div></div>
        <div><label className="block text-sm font-medium">Recursos, repuestos o herramientas utilizados</label><textarea className="mt-1 min-h-20 w-full rounded-md border bg-background px-3 py-2" value={form.resources} onChange={(e) => setField("resources", e.target.value)} placeholder="Ej. Sello mecánico, grasa, herramientas..." /><VoiceDictation onTranscript={(text) => appendField("resources", text)} /></div>
        <MaterialCodePicker value={form.material_codes} onChange={(value) => setField("material_codes", value)} />
        <div><span className="mb-2 block text-sm font-medium">Participantes</span><div className="grid gap-2 sm:grid-cols-2">{workers.map((worker) => <label key={worker.id} className="flex items-center gap-2 rounded-md border p-2 text-sm"><input type="checkbox" checked={participantIds.includes(worker.id)} onChange={() => toggleParticipant(worker.id)} />{worker.full_name}</label>)}</div></div>
      </>}

      <div className="grid gap-4 md:grid-cols-2"><div><label className="block text-sm font-medium">Riesgos e identificación de peligros</label><textarea className="mt-1 min-h-20 w-full rounded-md border bg-background px-3 py-2" value={form.risks} onChange={(e) => setField("risks", e.target.value)} /><VoiceDictation onTranscript={(text) => appendField("risks", text)} /></div><div><label className="block text-sm font-medium">Observaciones</label><textarea className="mt-1 min-h-20 w-full rounded-md border bg-background px-3 py-2" value={form.observations} onChange={(e) => setField("observations", e.target.value)} /><VoiceDictation onTranscript={(text) => appendField("observations", text)} /></div></div>

      <div className="rounded-lg border border-sky-200 bg-sky-50/50 p-4"><div className="flex items-center justify-between gap-3"><div><h3 className="text-sm font-semibold">Evidencia fotográfica</h3><p className="text-xs text-muted-foreground">Hasta 2 fotos. Puedes tomar una foto directamente desde el teléfono.</p></div><Button type="button" variant="outline" onClick={() => photoInputRef.current?.click()} disabled={photos.length >= 2}><Camera className="mr-1 h-4 w-4" />Tomar / elegir foto</Button></div><input ref={photoInputRef} type="file" accept="image/*" capture="environment" multiple className="hidden" onChange={(e) => choosePhotos(e.target.files)} />{photos.length > 0 && <div className="mt-3 grid grid-cols-2 gap-3">{photos.map((photo) => <div key={photo.id} className="relative"><img src={photo.previewUrl} alt="Vista previa" className="h-28 w-full rounded-md object-cover" /><button type="button" onClick={() => removePhoto(photo.id)} className="absolute right-1 top-1 rounded-full bg-red-600 p-1 text-white" aria-label="Eliminar foto"><Trash2 className="h-4 w-4" /></button></div>)}</div>}</div>

      <div className="flex justify-end"><Button disabled={saving}><Save className="mr-2 h-4 w-4" />{saving ? "Enviando..." : completed ? "Enviar trabajo realizado" : "Enviar solicitud de atención"}</Button></div>
    </form>
  );
}
