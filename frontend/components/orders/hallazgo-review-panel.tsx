"use client";

import { useEffect, useState } from "react";
import { CheckCircle, Loader2, RotateCcw, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { AreaNode, WorkOrderRecord } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { MaterialCodePicker } from "@/components/orders/material-code-picker";
import { usePlantAreaOptions } from "@/lib/use-plant-area-options";

const inputClass = "mt-1 w-full rounded-md border bg-background px-3 py-2";

export function HallazgoReviewPanel({
  wo,
  onUpdated,
}: {
  wo: WorkOrderRecord;
  onUpdated: (wo: WorkOrderRecord) => void;
}) {
  const [areas, setAreas] = useState<AreaNode[]>([]);
  const [workers, setWorkers] = useState<{ id: number; full_name: string }[]>([]);
  const plantAreaOptions = usePlantAreaOptions();
  const [plantArea, setPlantArea] = useState(wo.plant_area || "");
  const [sectionId, setSectionId] = useState(wo.area_id ? String(wo.area_id) : "");
  const [equipmentId, setEquipmentId] = useState(wo.equipment_id ? String(wo.equipment_id) : "");
  const [responsible, setResponsible] = useState("");
  const [participants, setParticipants] = useState<number[]>([]);
  const [maintenanceType, setMaintenanceType] = useState<string>(wo.maintenance_type || "CORRECTIVE");
  const [folio, setFolio] = useState(wo.folio || "");
  const [voucherNumber, setVoucherNumber] = useState(wo.voucher_number || "");
  const [voucherDate, setVoucherDate] = useState(wo.voucher_date || "");
  const [materialCodes, setMaterialCodes] = useState(wo.material_codes || "");
  const [scheduledDate, setScheduledDate] = useState(wo.scheduled_date || "");
  const [dueDate, setDueDate] = useState(wo.due_date || "");
  const [lotoControls, setLotoControls] = useState<string[]>(wo.loto_controls?.length ? wo.loto_controls : ["NOT_APPLICABLE"]);
  const [resources, setResources] = useState(wo.resources_required || "");
  const [notes, setNotes] = useState("");
  const [isExternalWork, setIsExternalWork] = useState(wo.is_external_work);
  const [externalExecutorName, setExternalExecutorName] = useState(wo.external_executor_name || "");
  const [externalCompany, setExternalCompany] = useState(wo.external_company || "");
  const [externalQuoteNumber, setExternalQuoteNumber] = useState(wo.external_quote_number || "");
  const [externalOcNumber, setExternalOcNumber] = useState(wo.external_oc_number || "");
  const [externalInvoiceNumber, setExternalInvoiceNumber] = useState(wo.external_invoice_number || "");
  const [externalAccountNumber, setExternalAccountNumber] = useState(wo.external_account_number || "");
  const [externalOcAmount, setExternalOcAmount] = useState(wo.external_oc_amount || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api.getCached<AreaNode[]>("/api/catalogs/tree", 300000),
      api.get<{ id: number; full_name: string }[]>("/api/users/workers"),
    ])
      .then(([tree, users]) => {
        setAreas(tree);
        setWorkers(users);
      })
      .catch(() => {
        setAreas([]);
        setWorkers([]);
      });
  }, []);

  const selectedSection = areas.find((area) => String(area.id) === sectionId);

  async function review(action: "ACCEPT" | "RETURN" | "REJECT") {
    setBusy(true);
    setError("");
    try {
      const payload: Record<string, unknown> = {
        action,
        notes: notes.trim() || null,
      };
      if (action === "ACCEPT") {
        Object.assign(payload, {
          plant_area: plantArea.trim() || null,
          area_id: sectionId ? Number(sectionId) : null,
          folio: folio.trim() || null,
          voucher_number: voucherNumber.trim() || null,
          voucher_date: voucherDate || null,
          material_codes: materialCodes.trim() || null,
          equipment_id: equipmentId ? Number(equipmentId) : null,
          is_external_work: isExternalWork,
          external_executor_name: isExternalWork ? externalExecutorName.trim() || null : null,
          external_company: isExternalWork ? externalCompany.trim() || null : null,
          external_quote_number: isExternalWork ? externalQuoteNumber.trim() || null : null,
          external_oc_number: isExternalWork ? externalOcNumber.trim() || null : null,
          external_invoice_number: isExternalWork ? externalInvoiceNumber.trim() || null : null,
          external_account_number: isExternalWork ? externalAccountNumber.trim() || null : null,
          external_oc_amount: isExternalWork ? externalOcAmount.trim() || null : null,
        });
        if (wo.hallazgo_kind === "REQUIRES_ATTENTION") {
          Object.assign(payload, {
            maintenance_type: maintenanceType,
            scheduled_date: scheduledDate || null,
            due_date: dueDate || null,
            loto_controls: lotoControls,
            resources_required: resources.trim() || null,
            ...(isExternalWork
              ? {}
              : {
                  responsible_user_id: Number(responsible) || null,
                  participant_user_ids: participants,
                }),
          });
        }
      }
      const updated = await api.post<WorkOrderRecord>(`/api/work-orders/${wo.id}/hallazgo-review`, payload);
      onUpdated(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo actualizar el hallazgo");
    } finally {
      setBusy(false);
    }
  }

  function toggleParticipant(id: number) {
    setParticipants((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  }

  function toggleLoto(value: string) {
    if (value === "NOT_APPLICABLE") {
      setLotoControls(["NOT_APPLICABLE"]);
      return;
    }
    setLotoControls((current) => {
      const next = current.filter((item) => item !== "NOT_APPLICABLE");
      const updated = next.includes(value) ? next.filter((item) => item !== value) : [...next, value];
      return updated.length ? updated : ["NOT_APPLICABLE"];
    });
  }

  return (
    <div className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-4">
      <h3 className="font-semibold text-amber-950">Revisión de hallazgo — {wo.hallazgo_folio || wo.ot_number}</h3>
      <p className="mt-1 text-sm text-amber-900">
        {wo.hallazgo_kind === "COMPLETED"
          ? "El trabajador declara que el trabajo ya fue realizado. Al aceptar se cerrará como OT aprobada."
          : "El hallazgo necesita una OT. Puedes asignar personal interno o convertirlo en trabajo externo."}
      </p>

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="text-sm font-medium">Área general
          <select className={inputClass} value={plantArea} onChange={(event) => setPlantArea(event.target.value)}>
            <option value="">Selecciona un área</option>
            {plantAreaOptions.map((area) => <option key={`${area.id}-${area.name}`} value={area.name}>{area.name}</option>)}
          </select>
        </label>
        <label className="text-sm font-medium">Sección
          <select className={inputClass} value={sectionId} onChange={(event) => { setSectionId(event.target.value); setEquipmentId(""); }}>
            <option value="">Selecciona una sección</option>
            {areas.map((section) => <option key={section.id} value={section.id}>{section.name}</option>)}
          </select>
        </label>
        <label className="text-sm font-medium">Equipo <span className="font-normal">(opcional)</span>
          <select className={inputClass} value={equipmentId} disabled={!sectionId} onChange={(event) => setEquipmentId(event.target.value)}>
            <option value="">Sin equipo específico</option>
            {(selectedSection?.equipment || []).map((equipment) => <option key={equipment.id} value={equipment.id}>{equipment.name}</option>)}
          </select>
        </label>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="text-sm font-medium">Folio <span className="font-normal">(opcional)</span>
          <input className={inputClass} value={folio} onChange={(event) => setFolio(event.target.value)} placeholder="Folio de la OT" />
        </label>
        <label className="text-sm font-medium">N.º de vale <span className="font-normal">(opcional)</span>
          <input className={inputClass} value={voucherNumber} onChange={(event) => setVoucherNumber(event.target.value)} placeholder="Número de vale" />
        </label>
        <label className="text-sm font-medium">Fecha de vale
          <input type="date" className={inputClass} value={voucherDate} onChange={(event) => setVoucherDate(event.target.value)} />
        </label>
      </div>

      <div className="mt-3"><MaterialCodePicker value={materialCodes} onChange={setMaterialCodes} /></div>

      <div className="mt-3 rounded-lg border border-cyan-200 bg-cyan-50/60 p-3">
        <label className="flex cursor-pointer items-start gap-3">
          <input type="checkbox" checked={isExternalWork} onChange={(event) => setIsExternalWork(event.target.checked)} className="mt-1 h-4 w-4 rounded border-input" />
          <span>
            <span className="block text-sm font-medium text-cyan-950">Trabajo realizado por externo</span>
            <span className="mt-0.5 block text-xs text-cyan-900/80">La persona externa no necesita una cuenta en la aplicación. El administrador quedará como coordinador.</span>
          </span>
        </label>
        {isExternalWork && (
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <label className="text-sm font-medium">Persona externa *<input className={inputClass} value={externalExecutorName} onChange={(event) => setExternalExecutorName(event.target.value)} placeholder="Nombre y apellido" maxLength={200} /></label>
            <label className="text-sm font-medium">Empresa contratista<input className={inputClass} value={externalCompany} onChange={(event) => setExternalCompany(event.target.value)} placeholder="Empresa (opcional)" maxLength={200} /></label>
            <label className="text-sm font-medium">N.º cotización<input className={inputClass} value={externalQuoteNumber} onChange={(event) => setExternalQuoteNumber(event.target.value)} placeholder="Número de cotización" maxLength={80} /></label>
            <label className="text-sm font-medium">N.º OC<input className={inputClass} value={externalOcNumber} onChange={(event) => setExternalOcNumber(event.target.value)} placeholder="Orden de compra" maxLength={80} /></label>
            <label className="text-sm font-medium">N.º factura<input className={inputClass} value={externalInvoiceNumber} onChange={(event) => setExternalInvoiceNumber(event.target.value)} placeholder="Factura" maxLength={80} /></label>
            <label className="text-sm font-medium">N.º cuenta<input className={inputClass} value={externalAccountNumber} onChange={(event) => setExternalAccountNumber(event.target.value)} placeholder="Cuenta" maxLength={80} /></label>
            <label className="text-sm font-medium">Monto OC<input className={inputClass} value={externalOcAmount} onChange={(event) => setExternalOcAmount(event.target.value)} placeholder="Monto" maxLength={80} /></label>
          </div>
        )}
      </div>

      {wo.hallazgo_kind === "REQUIRES_ATTENTION" && (
        <div className="mt-3 space-y-3">
          {!isExternalWork && (
            <>
              <label className="block text-sm font-medium">Trabajador responsable
                <select className={inputClass} value={responsible} onChange={(event) => setResponsible(event.target.value)}>
                  <option value="">Selecciona un trabajador</option>
                  {workers.map((worker) => <option key={worker.id} value={worker.id}>{worker.full_name}</option>)}
                </select>
              </label>
              <div>
                <span className="text-sm font-medium">Participantes</span>
                <div className="mt-1 grid gap-2 sm:grid-cols-2">
                  {workers.map((worker) => (
                    <label key={worker.id} className="flex items-center gap-2 rounded-md border bg-background p-2 text-sm">
                      <input type="checkbox" checked={participants.includes(worker.id) || String(worker.id) === responsible} disabled={String(worker.id) === responsible} onChange={() => toggleParticipant(worker.id)} />
                      {worker.full_name}
                    </label>
                  ))}
                </div>
              </div>
            </>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm font-medium">Tipo de mantenimiento
              <select className={inputClass} value={maintenanceType} onChange={(event) => setMaintenanceType(event.target.value)}>
                <option value="PREVENTIVE">Preventivo</option><option value="CORRECTIVE">Correctivo</option><option value="PREDICTIVE">Predictivo</option><option value="PROYECTO">Proyecto</option><option value="MONTAJE">Montaje</option><option value="URGENTE">Urgente</option>
              </select>
            </label>
            <label className="text-sm font-medium">Fecha programada<input type="date" className={inputClass} value={scheduledDate} onChange={(event) => setScheduledDate(event.target.value)} /></label>
            <label className="text-sm font-medium">Fecha límite<input type="date" className={inputClass} value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></label>
          </div>

          <div>
            <span className="text-sm font-medium">LOTO / AST</span>
            <div className="mt-1 grid gap-2 sm:grid-cols-2">
              {[['LOTO_BLOQUEO', 'LOTO / Bloqueo'], ['AST', 'AST'], ['TARJETA_ROJA', 'Tarjeta roja'], ['CHECKLIST_HERRAMIENTAS', 'Checklist herramientas'], ['NOT_APPLICABLE', 'No aplica']].map(([value, label]) => (
                <label key={value} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={lotoControls.includes(value)} onChange={() => toggleLoto(value)} />{label}</label>
              ))}
            </div>
          </div>
          <label className="block text-sm font-medium">Recursos requeridos<textarea className={inputClass} rows={2} value={resources} onChange={(event) => setResources(event.target.value)} /></label>
        </div>
      )}

      <textarea className={`${inputClass} mt-3 text-sm`} rows={2} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Observación de la revisión (opcional)" />
      {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button disabled={busy} onClick={() => review("ACCEPT")}><CheckCircle className="mr-1 h-4 w-4" />{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Aceptar y convertir en OT"}</Button>
        <Button variant="outline" disabled={busy} onClick={() => review("RETURN")}><RotateCcw className="mr-1 h-4 w-4" />Devolver</Button>
        <Button variant="destructive" disabled={busy} onClick={() => review("REJECT")}><XCircle className="mr-1 h-4 w-4" />Rechazar</Button>
      </div>
    </div>
  );
}
