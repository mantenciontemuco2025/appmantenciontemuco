"use client";

import { useState } from "react";
import { Loader2, Pencil, Send, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";
import type { WorkOrderRecord } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { MaterialCodePicker } from "@/components/orders/material-code-picker";

export function HallazgoEditPanel({
  wo,
  onUpdated,
  onDeleted,
}: {
  wo: WorkOrderRecord;
  onUpdated: (wo: WorkOrderRecord) => void;
  onDeleted: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [title, setTitle] = useState(wo.title || "");
  const [description, setDescription] = useState(wo.description || "");
  const [reportDate, setReportDate] = useState(wo.execution_date || wo.request_date || "");
  const [priority, setPriority] = useState<string>(wo.hallazgo_priority || "NORMAL");
  const [risks, setRisks] = useState(wo.risks || "");
  const [observations, setObservations] = useState(wo.observations || "");
  const [folio, setFolio] = useState(wo.folio || "");
  const [voucherNumber, setVoucherNumber] = useState(wo.voucher_number || "");
  const [materialCodes, setMaterialCodes] = useState(wo.material_codes || "");
  const [deleteReason, setDeleteReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    if (!title.trim() || !description.trim() || !reportDate) {
      setError("Completa el título, la descripción y la fecha del hallazgo.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const updated = await api.patch<WorkOrderRecord>(`/api/work-orders/${wo.id}/hallazgo`, {
        title: title.trim(),
        description: description.trim(),
        report_date: reportDate,
        priority,
        risks: risks.trim() || null,
        observations: observations.trim() || null,
        folio: folio.trim() || null,
        voucher_number: voucherNumber.trim() || null,
        material_codes: materialCodes.trim() || null,
        resubmit: true,
      });
      onUpdated(updated);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar el hallazgo.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (deleteReason.trim().length < 8) {
      setError("Escribe una observación de al menos 8 caracteres para eliminarlo.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.del(`/api/work-orders/${wo.id}/hallazgo`, { reason: deleteReason.trim() });
      onDeleted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo eliminar el hallazgo.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mb-4 rounded-xl border border-blue-200 bg-blue-50/60 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-blue-950">Hallazgo creado por ti</h2>
          <p className="mt-1 text-sm text-blue-900">
            Puedes corregirlo o eliminarlo mientras siga como hallazgo y no se haya convertido en OT.
          </p>
          {wo.hallazgo_status === "RETURNED" && wo.hallazgo_review_notes && (
            <p className="mt-2 text-sm text-orange-900"><strong>Observación del administrador:</strong> {wo.hallazgo_review_notes}</p>
          )}
        </div>
        {!editing && !deleting && (
          <div className="flex gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => { setEditing(true); setError(""); }}>
              <Pencil className="mr-1 h-4 w-4" /> Editar
            </Button>
            <Button type="button" variant="outline" size="sm" className="text-red-700" onClick={() => { setDeleting(true); setError(""); }}>
              <Trash2 className="mr-1 h-4 w-4" /> Eliminar
            </Button>
          </div>
        )}
      </div>

      {editing && (
        <div className="mt-4 space-y-3 border-t border-blue-200 pt-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm font-medium">Título
              <input className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={title} onChange={(e) => setTitle(e.target.value)} />
            </label>
            <label className="text-sm font-medium">Fecha del hecho
              <input type="date" className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={reportDate} onChange={(e) => setReportDate(e.target.value)} />
            </label>
          </div>
          <label className="block text-sm font-medium">Descripción
            <textarea className="mt-1 w-full rounded-md border bg-background px-3 py-2" rows={4} value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm font-medium">Prioridad
              <select className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={priority} onChange={(e) => setPriority(e.target.value)}>
                <option value="NORMAL">Normal</option><option value="URGENT">Urgente</option><option value="EMERGENCY">Emergencia</option>
              </select>
            </label>
            <label className="text-sm font-medium">Riesgos
              <input className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={risks} onChange={(e) => setRisks(e.target.value)} />
            </label>
            <label className="text-sm font-medium">Folio
              <input className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={folio} onChange={(e) => setFolio(e.target.value)} />
            </label>
            <label className="text-sm font-medium">N.º de vale
              <input className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={voucherNumber} onChange={(e) => setVoucherNumber(e.target.value)} />
            </label>
          </div>
          <div><MaterialCodePicker value={materialCodes} onChange={setMaterialCodes} /></div>
          <label className="block text-sm font-medium">Observaciones
            <textarea className="mt-1 w-full rounded-md border bg-background px-3 py-2" rows={2} value={observations} onChange={(e) => setObservations(e.target.value)} />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={() => void submit()} disabled={busy}>
              {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Send className="mr-1 h-4 w-4" />}
              Guardar y enviar a revisión
            </Button>
            <Button type="button" variant="outline" onClick={() => { setEditing(false); setError(""); }} disabled={busy}><X className="mr-1 h-4 w-4" />Cancelar</Button>
          </div>
        </div>
      )}

      {deleting && (
        <div className="mt-4 space-y-3 border-t border-blue-200 pt-4">
          <p className="text-sm font-medium text-red-800">El hallazgo dejará de aparecer en la aplicación. La observación quedará guardada en el historial.</p>
          <label className="block text-sm font-medium">Observación: ¿por qué lo eliminas?
            <textarea className="mt-1 w-full rounded-md border bg-background px-3 py-2" rows={3} maxLength={2000} value={deleteReason} onChange={(e) => setDeleteReason(e.target.value)} placeholder="Indica el error o motivo de eliminación" />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="destructive" onClick={() => void remove()} disabled={busy || deleteReason.trim().length < 8}>
              {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Trash2 className="mr-1 h-4 w-4" />}Confirmar eliminación
            </Button>
            <Button type="button" variant="outline" onClick={() => { setDeleting(false); setDeleteReason(""); setError(""); }} disabled={busy}><X className="mr-1 h-4 w-4" />Cancelar</Button>
          </div>
        </div>
      )}
      {error && <p className="mt-3 rounded-md bg-red-100 p-2 text-sm text-red-800" role="alert">{error}</p>}
    </section>
  );
}
