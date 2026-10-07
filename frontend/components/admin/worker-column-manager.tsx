"use client";

import { useEffect, useState } from "react";
import { CalendarSync, Columns3, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { User, WorkerColumn } from "@/lib/types";
import { Select } from "@/components/ui/select";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Button } from "@/components/ui/button";

type MonthlyMaterialsBackfillResult = {
  year: number;
  month: number;
  matched: number;
  queued: number;
  already_queued: number;
};

function currentMonthValue() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

/** Admin assignment of the ten existing worker columns in the monthly sheet. */
export function WorkerColumnManager() {
  const [columns, setColumns] = useState<WorkerColumn[]>([]);
  const [workers, setWorkers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [syncMonth, setSyncMonth] = useState(currentMonthValue);
  const [syncingMaterials, setSyncingMaterials] = useState(false);
  const [syncResult, setSyncResult] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [columnData, workerData] = await Promise.all([
        api.get<WorkerColumn[]>("/api/admin/worker-columns"),
        api.get<User[]>("/api/users/workers"),
      ]);
      setColumns(columnData);
      setWorkers(workerData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron cargar las posiciones.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function assign(slot: number, value: string) {
    const userId = value ? Number(value) : null;
    setBusy(slot);
    setError("");
    try {
      const updated = await api.put<WorkerColumn>(`/api/admin/worker-columns/${slot}`, { user_id: userId });
      setColumns((current) => current.map((column) => column.slot === slot ? updated : column));
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar la posición.");
    } finally {
      setBusy(null);
    }
  }

  async function syncMonthlyMaterials() {
    const [year, month] = syncMonth.split("-").map(Number);
    if (!year || !month) {
      setError("Selecciona un mes válido.");
      return;
    }
    setSyncingMaterials(true);
    setError("");
    setSyncResult("");
    try {
      const result = await api.post<MonthlyMaterialsBackfillResult>(
        "/api/work-orders/monthly-materials/backfill",
        { year, month }
      );
      const activeMessage = result.already_queued
        ? ` ${result.already_queued} ya estaban en proceso.`
        : "";
      setSyncResult(
        result.matched === 0
          ? "No se encontraron OT emitidas con códigos de materiales en ese mes."
          : `Se encontraron ${result.matched} OT y se enviaron ${result.queued} a sincronización.${activeMessage}`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar la sincronización.");
    } finally {
      setSyncingMaterials(false);
    }
  }

  const assignedIds = new Set(columns.map((column) => column.user_id).filter((id): id is number => id !== null));

  return (
    <section className="space-y-6">
      <div className="rounded-lg border bg-card p-4">
        <div className="mb-3 flex items-start gap-2">
          <CalendarSync className="mt-0.5 h-5 w-5" />
          <div>
            <h3 className="font-semibold">Registrar materiales de OT existentes</h3>
            <p className="text-sm text-muted-foreground">
              Actualiza las mismas filas del registro mensual con el código y nombre del material, sin duplicar OT.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="grid gap-1 text-sm font-medium">
            Mes a sincronizar
            <input
              type="month"
              value={syncMonth}
              onChange={(event) => setSyncMonth(event.target.value)}
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
            />
          </label>
          <Button onClick={syncMonthlyMaterials} disabled={syncingMaterials || !syncMonth}>
            {syncingMaterials ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CalendarSync className="mr-2 h-4 w-4" />}
            {syncingMaterials ? "Preparando..." : "Sincronizar materiales del mes"}
          </Button>
        </div>
        {syncResult && (
          <InlineAlert variant="success" className="mt-3" onDismiss={() => setSyncResult("")}>
            {syncResult}
          </InlineAlert>
        )}
      </div>

      <div>
      <div className="mb-4 flex items-center gap-2">
        <Columns3 className="h-5 w-5" />
        <div>
          <h3 className="text-lg font-semibold">Columnas del registro mensual</h3>
          <p className="text-xs text-muted-foreground">
            Asigna cada trabajador a una de las 10 columnas existentes (G:P).
          </p>
        </div>
      </div>

      {error && <InlineAlert variant="error" className="mb-3" onDismiss={() => setError("")}>{error}</InlineAlert>}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Cargando posiciones...
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left">
              <tr>
                <th className="px-3 py-2 font-medium">Posición</th>
                <th className="px-3 py-2 font-medium">Columna</th>
                <th className="px-3 py-2 font-medium">Trabajador</th>
              </tr>
            </thead>
            <tbody>
              {columns.map((column) => {
                const options = workers
                  .filter((worker) => worker.id === column.user_id || !assignedIds.has(worker.id))
                  .map((worker) => ({ value: String(worker.id), label: worker.full_name }));
                return (
                  <tr key={column.slot} className="border-t">
                    <td className="px-3 py-2">{column.slot}</td>
                    <td className="px-3 py-2 font-mono">{column.column_letter} · {column.column_key}</td>
                    <td className="min-w-[240px] px-3 py-2">
                      <Select
                        options={options}
                        placeholder="Sin asignar"
                        value={column.user_id ? String(column.user_id) : ""}
                        onChange={(event) => assign(column.slot, event.target.value)}
                        disabled={busy === column.slot}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      </div>
    </section>
  );
}
