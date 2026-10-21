"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Loader2, LockKeyhole } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { PageLoading } from "@/components/ui/page-loading";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import type { EquipmentLifeWorkOrderView } from "@/lib/types";

function dateLabel(value: string | null) {
  if (!value) return "—";
  const [year, month, day] = value.slice(0, 10).split("-");
  return day && month && year ? `${day}-${month}-${year}` : value;
}

function durationLabel(minutes: number | null) {
  if (minutes == null || minutes <= 0) return "—";
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return [hours ? `${hours} h` : "", remainder ? `${remainder} min` : ""]
    .filter(Boolean)
    .join(" ") || "0 min";
}

function DetailField({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value?.trim()) return null;
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="mt-1 whitespace-pre-wrap text-sm">{value}</div>
    </div>
  );
}

export default function EquipmentLifeWorkOrderPage({
  params,
}: {
  params: Promise<{ equipmentId: string; workOrderId: string }>;
}) {
  const { equipmentId, workOrderId } = use(params);
  const { user, loading, logout } = useAuth();
  const [record, setRecord] = useState<EquipmentLifeWorkOrderView | null>(null);
  const [loadingRecord, setLoadingRecord] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user) return;
    let active = true;
    setLoadingRecord(true);
    setError("");
    api.get<EquipmentLifeWorkOrderView>(
      `/api/equipment-life/equipment/${equipmentId}/work-orders/${workOrderId}`,
    )
      .then((data) => {
        if (active) setRecord(data);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "No se pudo cargar la OT.");
      })
      .finally(() => {
        if (active) setLoadingRecord(false);
      });
    return () => {
      active = false;
    };
  }, [user, equipmentId, workOrderId]);

  if (loading || !user) {
    return <PageLoading message={loading ? "Validando sesión..." : "Redirigiendo..."} />;
  }

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href="/hojas-vida" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
            <ArrowLeft className="h-4 w-4" /> Volver a hojas de vida
          </Link>
          <h1 className="mt-2 text-2xl font-bold">Detalle de orden de trabajo</h1>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border bg-muted px-3 py-1.5 text-xs font-medium text-muted-foreground">
          <LockKeyhole className="h-3.5 w-3.5" /> Solo lectura
        </span>
      </div>

      {loadingRecord && (
        <div className="flex items-center gap-2 rounded-lg border p-5 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Cargando orden...
        </div>
      )}
      {!loadingRecord && error && (
        <div className="space-y-3">
          <InlineAlert variant="error">{error}</InlineAlert>
          <Link href="/hojas-vida"><Button variant="outline">Volver a hojas de vida</Button></Link>
        </div>
      )}
      {!loadingRecord && record && (
        <article className="rounded-xl border bg-card p-5 shadow-sm">
          <header className="mb-5 flex flex-wrap items-start justify-between gap-3 border-b pb-4">
            <div>
              <p className="font-mono text-sm font-semibold text-primary">{record.ot_number}</p>
              {record.original_ot_number && (
                <p className="mt-1 text-xs text-muted-foreground">OT original: {record.original_ot_number}</p>
              )}
              <h2 className="mt-2 text-xl font-semibold">{record.title}</h2>
            </div>
            <div className="flex gap-2">
              <span className="rounded-full bg-blue-50 px-3 py-1 text-sm text-blue-800">{record.status}</span>
              <span className="rounded-full bg-muted px-3 py-1 text-sm">{record.maintenance_type}</span>
            </div>
          </header>

          <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <DetailField label="Fecha" value={dateLabel(record.event_date)} />
            <DetailField label="Área" value={record.plant_area_name} />
            <DetailField label="Sección" value={record.section_name} />
            <DetailField label="Equipo" value={record.equipment_name} />
            <DetailField label="Realizado por" value={record.performed_by} />
            <DetailField label="Participantes" value={record.participants.join(", ") || null} />
            <DetailField label="Tiempo trabajado" value={durationLabel(record.worked_duration_minutes)} />
            <DetailField label="Folio" value={record.folio} />
            <DetailField label="N.º de vale" value={record.voucher_number} />
            <DetailField label="Fecha de vale" value={dateLabel(record.voucher_date)} />
            <DetailField label="Códigos de materiales" value={record.material_codes} />
          </div>

          <div className="grid gap-3">
            <DetailField label="Descripción del trabajo" value={record.description} />
            <DetailField label="Trabajo realizado / observaciones" value={record.completion_notes || record.observations} />
            {record.completion_notes && record.observations && record.completion_notes !== record.observations && (
              <DetailField label="Observaciones de la OT" value={record.observations} />
            )}
            <DetailField label="Recursos utilizados" value={record.resources_required} />
            <DetailField label="Riesgos informados" value={record.risks} />
          </div>
        </article>
      )}
    </Shell>
  );
}
