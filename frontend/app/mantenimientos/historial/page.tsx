"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ChevronDown, Loader2, SearchX, Wrench } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import type { AreaNode, MaintenanceListItem } from "@/lib/types";
import { Select } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { SyncBadge } from "@/components/maintenance/sync-badge";
import { formatDuration } from "@/lib/utils";
import { maintenanceTypeLabel } from "@/lib/status";
import { EmptyState } from "@/components/ui/empty-state";
import { InlineAlert } from "@/components/ui/inline-alert";
import { PageLoading } from "@/components/ui/page-loading";

const PAGE_SIZE = 20;

export default function HistorialPage() {
  // useSearchParams() must sit inside a Suspense boundary for SSG/prerender.
  return (
    <Suspense fallback={<PageLoading message="Cargando historial..." />}>
      <HistorialContent />
    </Suspense>
  );
}

function HistorialContent() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [records, setRecords] = useState<MaintenanceListItem[]>([]);
  const [areas, setAreas] = useState<AreaNode[]>([]);
  const [loadingRecords, setLoadingRecords] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState("");

  const [fDate, setFDate] = useState("");
  const [fArea, setFArea] = useState("");
  const [fType, setFType] = useState("");

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);

  useEffect(() => {
    loadFirstPage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, fDate, fArea, fType]);

  async function loadFirstPage() {
    setLoadingRecords(true);
    setError("");
    setHasMore(true);
    try {
      const page = await fetchPage(0);
      setRecords(page);
      setHasMore(page.length === PAGE_SIZE);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al cargar el historial");
      setRecords([]);
    } finally {
      setLoadingRecords(false);
    }
  }

  async function loadMore() {
    setLoadingMore(true);
    try {
      const page = await fetchPage(records.length);
      setRecords((prev) => [...prev, ...page]);
      setHasMore(page.length === PAGE_SIZE);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al cargar más registros");
    } finally {
      setLoadingMore(false);
    }
  }

  function fetchPage(offset: number) {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (fDate) params.set("date", fDate);
    if (fArea) params.set("area_id", fArea);
    if (fType) params.set("maintenance_type", fType);
    return api.get<MaintenanceListItem[]>(`/api/maintenance?${params.toString()}`);
  }

  useEffect(() => {
    api
      .get<AreaNode[]>("/api/catalogs/tree")
      .then(setAreas)
      .catch(() => setAreas([]));
  }, []);

  // Show a success notice after creating a record
  const justCreated = searchParams.get("created") === "1";

  if (loading || !user) {
    return <PageLoading message={loading ? "Validando sesión..." : "Redirigiendo al inicio de sesión..."} />;
  }

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      <h1 className="mb-4 text-xl font-bold">Historial de mantenciones</h1>

      {justCreated && (
        <InlineAlert variant="success" className="mb-4">
          Mantención registrada correctamente.
        </InlineAlert>
      )}

      {/* Filters */}
      <div className="mb-4 space-y-3 rounded-lg border bg-card p-3 sm:grid sm:grid-cols-3 sm:gap-3 sm:space-y-0">
        <div>
          <label className="text-sm font-medium block mb-1.5">Fecha</label>
          <Input
            type="date"
            value={fDate}
            onChange={(e) => setFDate(e.target.value)}
          />
        </div>
        <Select
          label="Área"
          options={areas.map((a) => ({ value: String(a.id), label: a.name }))}
          value={fArea}
          onChange={(e) => setFArea(e.target.value)}
        />
        <Select
          label="Tipo"
          options={[
            { value: "PREVENTIVE", label: "Preventivo" },
            { value: "CORRECTIVE", label: "Correctivo" },
            { value: "PREDICTIVE", label: "Predictivo" },
            { value: "PROYECTO", label: "Proyecto" },
            { value: "MONTAJE", label: "Montaje" },
          ]}
          value={fType}
          onChange={(e) => setFType(e.target.value)}
        />
      </div>

      {error && (
        <InlineAlert variant="error" className="mb-4" onDismiss={() => setError("")}>
          {error}
        </InlineAlert>
      )}

      {loadingRecords ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
        </div>
      ) : records.length === 0 ? (
        <EmptyState
          icon={<SearchX className="h-6 w-6" />}
          title="No se encontraron registros"
          description="Pruebe cambiando los filtros o registre una nueva mantención."
          action={
            <Button variant="outline" size="sm" onClick={() => loadFirstPage()}>
              Recargar
            </Button>
          }
        />
      ) : (
        <>
          <ul className="space-y-2">
            {records.map((r) => (
              <li key={r.id} className="rounded-lg border bg-card p-4 transition-shadow hover:shadow-sm">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                        <Wrench className="h-3.5 w-3.5" />
                      </span>
                      <div className="font-semibold truncate">{r.equipment.name}</div>
                    </div>
                    <div className="pl-9 text-sm text-muted-foreground">
                      {r.area.name} · {r.section_name}
                    </div>
                    <div className="pl-9 text-sm text-muted-foreground">
                      {new Date(r.date).toLocaleDateString("es-CL")}
                    </div>
                    <div className="pl-9 text-sm text-muted-foreground">
                      {maintenanceTypeLabel(r.maintenance_type)} · {formatDuration(r.duration_minutes)}
                    </div>
                  </div>
                  <SyncBadge status={r.sheet_sync_status} />
                </div>
              </li>
            ))}
          </ul>

          {/* Footer — contador + Cargar más */}
          <div className="mt-4 flex flex-col items-center gap-3">
            <p className="text-xs text-muted-foreground">
              Mostrando {records.length} registro{records.length === 1 ? "" : "s"}
            </p>
            {hasMore ? (
              <Button variant="outline" onClick={loadMore} disabled={loadingMore} className="w-full sm:w-auto">
                {loadingMore ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <ChevronDown className="mr-2 h-4 w-4" />
                )}
                Cargar más
              </Button>
            ) : (
              <p className="text-xs text-muted-foreground">Fin de la lista</p>
            )}
          </div>
        </>
      )}
    </Shell>
  );
}
