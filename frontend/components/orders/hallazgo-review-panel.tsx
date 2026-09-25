"use client";

import { useEffect, useState } from "react";
import { CheckCircle, Loader2, RotateCcw, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { AreaNode, WorkOrderRecord } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { MaterialCodePicker } from "@/components/orders/material-code-picker";

function durationLabel(totalMinutes: number) {
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  const parts = [];
  if (hours) parts.push(`${hours} ${hours === 1 ? "hora" : "horas"}`);
  if (minutes || !parts.length) parts.push(`${minutes} ${minutes === 1 ? "minuto" : "minutos"}`);
  return parts.join(" ");
}

export function HallazgoReviewPanel({ wo, onUpdated }: { wo: WorkOrderRecord; onUpdated: (wo: WorkOrderRecord) => void }) {
  const [areas, setAreas] = useState<AreaNode[]>([]);
  const [workers, setWorkers] = useState<{ id: number; full_name: string }[]>([]);
  const [equipmentId, setEquipmentId] = useState(wo.equipment_id ? String(wo.equipment_id) : "");
  const [responsible, setResponsible] = useState("");
  const [participants, setParticipants] = useState<number[]>([]);
  const [maintenanceType, setMaintenanceType] = useState("CORRECTIVE");
  const [folio, setFolio] = useState(wo.folio || "");
  const [voucherNumber, setVoucherNumber] = useState(wo.voucher_number || "");
  const [materialCodes, setMaterialCodes] = useState(wo.material_codes || "");
  const [estimatedHours, setEstimatedHours] = useState("");
  const [estimatedMinutes, setEstimatedMinutes] = useState("");
  const [scheduledDate, setScheduledDate] = useState(wo.scheduled_date || "");
  const [dueDate, setDueDate] = useState("");
  const [lotoControls, setLotoControls] = useState<string[]>(["NOT_APPLICABLE"]);
  const [resources, setResources] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    Promise.all([
      api.getCached<AreaNode[]>("/api/catalogs/tree", 300000),
      api.get<{ id: number; full_name: string }[]>("/api/users/workers"),
    ]).then(([tree, users]) => { setAreas(tree); setWorkers(users); }).catch(() => { setAreas([]); setWorkers([]); });
  }, []);

  const selectedArea = areas.find((area) => area.id === wo.area_id);

  async function review(action: "ACCEPT" | "RETURN" | "REJECT") {
    setBusy(true); setError("");
    try {
      const updated = await api.post<WorkOrderRecord>(`/api/work-orders/${wo.id}/hallazgo-review`, {
        action, notes: notes.trim() || null,
        ...(action === "ACCEPT" ? {
          folio: folio.trim() || null,
          voucher_number: voucherNumber.trim() || null,
          material_codes: materialCodes.trim() || null,
          equipment_id: equipmentId ? Number(equipmentId) : null,
          ...(wo.hallazgo_kind === "REQUIRES_ATTENTION" ? {
            responsible_user_id: Number(responsible) || null,
            participant_user_ids: participants,
            maintenance_type: maintenanceType,
            estimated_time: estimatedHours || estimatedMinutes ? durationLabel((Number(estimatedHours) || 0) * 60 + (Number(estimatedMinutes) || 0)) : null,
            scheduled_date: scheduledDate || null,
            due_date: dueDate || null,
            loto_controls: lotoControls,
            resources_required: resources || null,
          } : {}),
        } : {}),
      });
      onUpdated(updated);
    } catch (err) { setError(err instanceof Error ? err.message : "No se pudo actualizar el hallazgo"); }
    finally { setBusy(false); }
  }

  function toggleParticipant(id: number) {
    setParticipants((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function toggleLoto(value: string) {
    if (value === "NOT_APPLICABLE") { setLotoControls(["NOT_APPLICABLE"]); return; }
    setLotoControls((current) => {
      const next = current.filter((item) => item !== "NOT_APPLICABLE");
      const updated = next.includes(value) ? next.filter((item) => item !== value) : [...next, value];
      return updated.length ? updated : ["NOT_APPLICABLE"];
    });
  }

  return <div className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-4">
    <h3 className="font-semibold text-amber-950">Revisión de hallazgo — {wo.hallazgo_folio || wo.ot_number}</h3>
    <p className="mt-1 text-sm text-amber-900">{wo.hallazgo_kind === "COMPLETED" ? "El trabajador declara que el trabajo ya fue realizado. Al aceptar se cerrará como OT aprobada." : "El hallazgo necesita una OT y un responsable para ejecutar el trabajo."}</p>
    <div className="mt-3 grid gap-3 sm:grid-cols-3"><label className="text-sm font-medium">Equipo <span className="font-normal">(opcional)</span><select className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={equipmentId} onChange={(e) => setEquipmentId(e.target.value)}><option value="">Sin equipo específico</option>{(selectedArea?.equipment || []).map((equipment) => <option key={equipment.id} value={equipment.id}>{equipment.name}</option>)}</select></label><label className="text-sm font-medium">Folio <span className="font-normal">(opcional)</span><input className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={folio} onChange={(e) => setFolio(e.target.value)} placeholder="Folio de la OT" /></label><label className="text-sm font-medium">N.º de vale <span className="font-normal">(opcional)</span><input className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={voucherNumber} onChange={(e) => setVoucherNumber(e.target.value)} placeholder="Número de vale" /></label></div>
    <div className="mt-3"><MaterialCodePicker value={materialCodes} onChange={setMaterialCodes} /></div>
    {wo.hallazgo_kind === "REQUIRES_ATTENTION" && <div className="mt-3 space-y-3"><label className="block text-sm font-medium">Trabajador responsable<select className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={responsible} onChange={(e) => setResponsible(e.target.value)}><option value="">Selecciona un trabajador</option>{workers.map((worker) => <option key={worker.id} value={worker.id}>{worker.full_name}</option>)}</select></label><div><span className="text-sm font-medium">Participantes</span><div className="mt-1 grid gap-2 sm:grid-cols-2">{workers.map((worker) => <label key={worker.id} className="flex items-center gap-2 rounded-md border bg-background p-2 text-sm"><input type="checkbox" checked={participants.includes(worker.id) || String(worker.id) === responsible} disabled={String(worker.id) === responsible} onChange={() => toggleParticipant(worker.id)} />{worker.full_name}</label>)}</div></div><div className="grid gap-3 sm:grid-cols-2"><label className="text-sm font-medium">Tipo de mantenimiento<select className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={maintenanceType} onChange={(e) => setMaintenanceType(e.target.value)}><option value="PREVENTIVE">Preventivo</option><option value="CORRECTIVE">Correctivo</option><option value="PREDICTIVE">Predictivo</option><option value="PROYECTO">Proyecto</option><option value="MONTAJE">Montaje</option><option value="URGENTE">Urgente</option></select></label><div><span className="text-sm font-medium">Tiempo estimado</span><div className="mt-1 grid grid-cols-2 gap-2"><label className="text-sm">Horas<input type="number" min="0" step="1" className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={estimatedHours} onChange={(e) => setEstimatedHours(e.target.value)} placeholder="0" /></label><label className="text-sm">Minutos<input type="number" min="0" max="59" step="1" className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={estimatedMinutes} onChange={(e) => setEstimatedMinutes(e.target.value)} placeholder="0 a 59" /></label></div></div><label className="text-sm font-medium">Fecha programada<input type="date" className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={scheduledDate} onChange={(e) => setScheduledDate(e.target.value)} /></label><label className="text-sm font-medium">Fecha límite<input type="date" className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={dueDate} onChange={(e) => setDueDate(e.target.value)} /></label></div><div><span className="text-sm font-medium">LOTO / AST</span><div className="mt-1 grid gap-2 sm:grid-cols-2">{[["LOTO_BLOQUEO", "LOTO / Bloqueo"], ["AST", "AST"], ["TARJETA_ROJA", "Tarjeta roja"], ["CHECKLIST_HERRAMIENTAS", "Checklist herramientas"], ["NOT_APPLICABLE", "No aplica"]].map(([value, label]) => <label key={value} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={lotoControls.includes(value)} onChange={() => toggleLoto(value)} />{label}</label>)}</div></div><label className="block text-sm font-medium">Recursos requeridos<textarea className="mt-1 w-full rounded-md border bg-background px-3 py-2" rows={2} value={resources} onChange={(e) => setResources(e.target.value)} /></label></div>}
    <textarea className="mt-3 w-full rounded-md border bg-background px-3 py-2 text-sm" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Observación de la revisión (opcional)" />
    {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
    <div className="mt-3 flex flex-wrap gap-2"><Button disabled={busy} onClick={() => review("ACCEPT")}><CheckCircle className="mr-1 h-4 w-4" />{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Aceptar y convertir en OT"}</Button><Button variant="outline" disabled={busy} onClick={() => review("RETURN")}><RotateCcw className="mr-1 h-4 w-4" />Devolver</Button><Button variant="destructive" disabled={busy} onClick={() => review("REJECT")}><XCircle className="mr-1 h-4 w-4" />Rechazar</Button></div>
  </div>;
}
