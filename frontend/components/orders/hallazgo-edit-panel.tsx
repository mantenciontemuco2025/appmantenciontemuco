"use client";

import { useState } from "react";
import { Loader2, Send } from "lucide-react";
import { api } from "@/lib/api";
import type { WorkOrderRecord } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { MaterialCodePicker } from "@/components/orders/material-code-picker";

export function HallazgoEditPanel({ wo, onUpdated }: { wo: WorkOrderRecord; onUpdated: (wo: WorkOrderRecord) => void }) {
  const [description, setDescription] = useState(wo.description || "");
  const [observations, setObservations] = useState(wo.observations || "");
  const [folio, setFolio] = useState(wo.folio || "");
  const [voucherNumber, setVoucherNumber] = useState(wo.voucher_number || "");
  const [materialCodes, setMaterialCodes] = useState(wo.material_codes || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit() {
    setBusy(true); setError("");
    try {
      const updated = await api.patch<WorkOrderRecord>(`/api/work-orders/${wo.id}/hallazgo`, { description, observations, folio, voucher_number: voucherNumber, material_codes: materialCodes, resubmit: true });
      onUpdated(updated);
    } catch (err) { setError(err instanceof Error ? err.message : "No se pudo reenviar el hallazgo"); }
    finally { setBusy(false); }
  }
  return <div className="mb-4 rounded-xl border border-orange-300 bg-orange-50 p-4"><h3 className="font-semibold text-orange-950">Hallazgo devuelto para corregir</h3><p className="mt-1 text-sm text-orange-900">{wo.hallazgo_review_notes || "El administrador solicitó una corrección."}</p><label className="mt-3 block text-sm font-medium">Descripción<textarea className="mt-1 w-full rounded-md border bg-background px-3 py-2" rows={4} value={description} onChange={(e) => setDescription(e.target.value)} /></label><label className="mt-3 block text-sm font-medium">Observaciones<textarea className="mt-1 w-full rounded-md border bg-background px-3 py-2" rows={2} value={observations} onChange={(e) => setObservations(e.target.value)} /></label><div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="text-sm font-medium">Folio <span className="font-normal">(opcional)</span><input className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={folio} onChange={(e) => setFolio(e.target.value)} /></label><label className="text-sm font-medium">N.º de vale <span className="font-normal">(opcional)</span><input className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={voucherNumber} onChange={(e) => setVoucherNumber(e.target.value)} /></label></div><div className="mt-3"><MaterialCodePicker value={materialCodes} onChange={setMaterialCodes} /></div>{error && <p className="mt-2 text-sm text-red-700">{error}</p>}<Button className="mt-3" disabled={busy} onClick={submit}>{busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Send className="mr-1 h-4 w-4" />}Reenviar a revisión</Button></div>;
}
