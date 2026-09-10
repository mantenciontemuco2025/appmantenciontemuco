"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Plus, Loader2, RefreshCw, Eye, Send, ClipboardList, ChevronDown, SearchX, SendHorizontal } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/layout/shell";
import type { WorkOrderListItem, WorkOrderCounter, WorkOrderStatus } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { PageLoading } from "@/components/ui/page-loading";
import { EmptyState } from "@/components/ui/empty-state";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { StatusBadge, maintenanceTypeLabel } from "@/lib/status";
import { SyncBadge } from "@/components/maintenance/sync-badge";
import { cn } from "@/lib/utils";

type TabKey = "ALL" | "DRAFT" | "PENDING" | "IN_PROGRESS" | "COMPLETED" | "APPROVED" | "CANCELLED" | "OVERDUE";

const TABS: { key: TabKey; label: string }[] = [
  { key: "ALL", label: "Todas" },
  { key: "DRAFT", label: "Borradores" },
  { key: "PENDING", label: "Pendientes" },
  { key: "IN_PROGRESS", label: "En proceso" },
  { key: "COMPLETED", label: "Finalizadas" },
  { key: "APPROVED", label: "Aprobadas" },
  { key: "CANCELLED", label: "Canceladas" },
  { key: "OVERDUE", label: "Vencidas" },
];

const PAGE_SIZE = 25;

export default function OrdenesPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [orders, setOrders] = useState<WorkOrderListItem[]>([]);
  const [loadingOrders, setLoadingOrders] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [actionId, setActionId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("ALL");
  const [searchOT, setSearchOT] = useState("");
  const [searchResponsible, setSearchResponsible] = useState("");
  const [counter, setCounter] = useState<WorkOrderCounter | null>(null);
  const [error, setError] = useState("");

  // Vencidas — ventana separada consultada al servidor (overdue=true).
  const [overdue, setOverdue] = useState<WorkOrderListItem[]>([]);
  const [loadingOverdue, setLoadingOverdue] = useState(false);

  // Emisión en lote — selección sobre filas DRAFT de la ventana cargada.
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [batchConfirming, setBatchConfirming] = useState(false);
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchResult, setBatchResult] = useState<{ issued: number[]; failures: { id: number; error: string }[] } | null>(null);

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    loadFirstPage();
    api
      .get<WorkOrderCounter>("/api/work-orders/counter")
      .then(setCounter)
      .catch(() => setCounter(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  // Carga el panel de Vencidas cuando se activa la pestaña (una vez por visita).
  useEffect(() => {
    if (!user || activeTab !== "OVERDUE" || loadingOverdue || overdue.length > 0) return;
    setLoadingOverdue(true);
    api
      .get<WorkOrderListItem[]>("/api/work-orders?overdue=true&limit=100")
      .then(setOverdue)
      .catch((err) => setError(err instanceof Error ? err.message : "Error al cargar vencidas"))
      .finally(() => setLoadingOverdue(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  // Poll mientras alguna OT visible esté en sincronización asíncrona (PENDING),
  // para que el badge pase solo a SYNCED/FAILED sin recargar manualmente.
  // Silencioso: no activa el spinner de carga → no hace parpadear la lista.
  const hasPendingSync = orders.some(
    (o) => o.ot_sheet_sync_status === "PENDING" || o.monthly_sheet_sync_status === "PENDING"
  );
  useEffect(() => {
    if (!hasPendingSync) return;
    const timer = setInterval(() => loadFirstPage(true), 4000);
    // Deja de pollear tras ~16s incluso si quedó PENDING: evita recargas
    // infinitas. El badge del detalle o un refresh manual cubre el resto.
    const stop = setTimeout(() => clearInterval(timer), 16000);
    return () => {
      clearInterval(timer);
      clearTimeout(stop);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasPendingSync]);

  async function loadFirstPage(silent = false) {
    if (!silent) setLoadingOrders(true);
    if (!silent) setError("");
    setHasMore(true);
    try {
      // Ventana acotada — nunca una lista infinita. "Cargar más" agrega el
      // siguiente tramo vía offset hasta llegar al final.
      const page = await api.get<WorkOrderListItem[]>(
        `/api/work-orders?limit=${PAGE_SIZE}&offset=0`
      );
      setOrders(page);
      setHasMore(page.length === PAGE_SIZE);
    } catch (err) {
      if (!silent) {
        setError(err instanceof Error ? err.message : "Error al cargar las órdenes");
        setOrders([]);
      }
    } finally {
      if (!silent) setLoadingOrders(false);
    }
  }

  async function loadMore() {
    setLoadingMore(true);
    try {
      const page = await api.get<WorkOrderListItem[]>(
        `/api/work-orders?limit=${PAGE_SIZE}&offset=${orders.length}`
      );
      setOrders((prev) => [...prev, ...page]);
      setHasMore(page.length === PAGE_SIZE);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al cargar más órdenes");
    } finally {
      setLoadingMore(false);
    }
  }

  async function syncMonthly(id: number) {
    setActionId(id);
    try {
      await api.post(`/api/work-orders/${id}/sync-monthly`);
      await loadFirstPage();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Error al sincronizar el mensual");
    } finally {
      setActionId(null);
    }
  }

  async function retryGoogleSync(id: number) {
    setActionId(id);
    try {
      await api.post(`/api/work-orders/${id}/sync-google`);
      await loadFirstPage();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Error al sincronizar con Google");
    } finally {
      setActionId(null);
    }
  }

  // ── Emisión en lote ──────────────────────────────────────────────────────
  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelected((prev) => {
      if (prev.size === selectable.length) return new Set();
      return new Set(selectable.map((o) => o.id));
    });
  }

  const selectable = orders.filter((o) => o.status === "DRAFT" && !o.submitted_for_review);

  async function confirmBatchIssue() {
    if (batchBusy) return;
    setBatchBusy(true);
    setBatchResult(null);
    try {
      const res = await api.post<{ issued: number[]; failures: { id: number; error: string }[] }>(
        "/api/work-orders/batch-issue",
        { ids: Array.from(selected) }
      );
      setBatchResult(res);
      setSelected(new Set());
      await loadFirstPage(true);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Error al emitir en lote");
    } finally {
      setBatchBusy(false);
    }
  }

  // Filtros en cliente sobre la ventana cargada (tabs + búsqueda).
  // La pestaña "Vencidas" usa su propia ventana consultada al servidor.
  const source = activeTab === "OVERDUE" ? overdue : orders;
  const filtered = source.filter((o) => {
    if (activeTab !== "ALL" && activeTab !== "OVERDUE" && o.status !== activeTab) return false;
    if (searchOT && !o.ot_number.toLowerCase().includes(searchOT.toLowerCase()) && !o.title.toLowerCase().includes(searchOT.toLowerCase())) return false;
    if (searchResponsible && o.responsible_user_name && !o.responsible_user_name.toLowerCase().includes(searchResponsible.toLowerCase())) return false;
    return true;
  });

  function tabCount(key: TabKey): number {
    if (key === "ALL") return orders.length;
    if (key === "OVERDUE") return overdue.length;
    return orders.filter((o) => o.status === key).length;
  }

  if (loading || !user) {
    return <PageLoading message={loading ? "Validando sesión..." : "Redirigiendo al inicio de sesión..."} />;
  }

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Órdenes de Trabajo</h1>
          <p className="text-muted-foreground">Gestión completa del ciclo de vida</p>
        </div>
        <div className="flex items-center gap-2">
          {counter && (
            <span className="inline-flex items-center gap-1.5 rounded-lg border bg-card px-3 py-2 text-sm">
              <ClipboardList className="h-4 w-4 text-primary" />
              <span className="font-semibold">{counter.total_all}</span>
              <span className="text-muted-foreground">OTs en total</span>
              <span className="ml-1 rounded-md bg-muted px-1.5 py-0.5 font-mono text-xs text-primary">
                próximo {counter.next_ot_number}
              </span>
            </span>
          )}
          <Link href="/ordenes/nuevo">
            <Button>
              <Plus className="mr-1 h-4 w-4" /> Nueva OT
            </Button>
          </Link>
        </div>
      </div>

      {/* Tabs */}
      <div className="mb-3 flex gap-1 overflow-x-auto border-b">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              "whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              activeTab === tab.key
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {tab.label}
            <span className="ml-1 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-muted px-1.5 text-xs">
              {tabCount(tab.key)}
            </span>
          </button>
        ))}
      </div>

      {/* Search filters */}
      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <input
          className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm"
          placeholder="Buscar N° OT o título..."
          value={searchOT}
          onChange={(e) => setSearchOT(e.target.value)}
        />
        <input
          className="rounded-md border border-input bg-background px-3 py-2 text-sm sm:w-48"
          placeholder="Responsable..."
          value={searchResponsible}
          onChange={(e) => setSearchResponsible(e.target.value)}
        />
      </div>

      {/* Emisión en lote — barra de selección (visible en pestañas con DRAFT) */}
      {user.role === "ADMIN" && activeTab !== "OVERDUE" && selectable.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-dashed bg-muted/30 px-3 py-2">
          <label className="inline-flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={selected.size > 0 && selected.size === selectable.length}
              onChange={toggleSelectAll}
              className="h-4 w-4 rounded border-input"
            />
            <span className="font-medium">Seleccionar todos</span>
          </label>
          {selected.size > 0 && (
            <Button size="sm" onClick={() => setBatchConfirming(true)}>
              <SendHorizontal className="mr-1 h-3.5 w-3.5" />
              Emitir {selected.size} seleccionad{selected.size === 1 ? "a" : "as"}
            </Button>
          )}
          <span className="text-xs text-muted-foreground">
            Selecciona borradores en la lista para emitirlos en lote.
          </span>
        </div>
      )}

      {/* Confirmación de emisión en lote */}
      {batchConfirming && (
        <ConfirmDialog
          title={`Emitir ${selected.size} OT${selected.size === 1 ? "" : "s"} en lote`}
          description="Las órdenes seleccionadas pasarán a Pendientes y se asignarán a sus responsables. Esta acción no se puede deshacer."
          confirmLabel="Emitir en lote"
          tone="default"
          busy={batchBusy}
          onConfirm={confirmBatchIssue}
          onCancel={() => setBatchConfirming(false)}
        >
          {batchResult && (
            <div className="mb-3 rounded-md border bg-muted/40 px-3 py-2 text-sm">
              <p className="font-medium">
                Emitidas: {batchResult.issued.length}{" "}
                {batchResult.issued.length === 1 ? "OT" : "OTs"}
              </p>
              {batchResult.failures.length > 0 && (
                <p className="mt-1 text-red-600">
                  Errores: {batchResult.failures.map((f) => `#${f.id}`).join(", ")}
                </p>
              )}
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => setBatchConfirming(false)}
              >
                Cerrar
              </Button>
            </div>
          )}
        </ConfirmDialog>
      )}

      {/* Order list */}
      {(activeTab === "OVERDUE" ? loadingOverdue : loadingOrders) ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
        </div>
      ) : error && filtered.length === 0 ? (
        <EmptyState
          icon={<SearchX className="h-6 w-6" />}
          title="No se pudieron cargar las órdenes"
          description={error}
        />
      ) : filtered.length === 0 ? (
        activeTab === "OVERDUE" ? (
          <EmptyState
            icon={<SearchX className="h-6 w-6" />}
            title="Sin órdenes vencidas"
            description="No hay OTs pendientes o en proceso con fecha límite pasada."
          />
        ) : (
          <EmptyState
            icon={<SearchX className="h-6 w-6" />}
            title="No hay órdenes que coincidan con los filtros"
            description="Pruebe cambiando la pestaña o los términos de búsqueda."
          />
        )
      ) : (
        <>
          <ul className="space-y-3">
            {filtered.map((o) => {
              const isOverdue =
                o.due_date &&
                new Date(o.due_date) < new Date() &&
                (o.status === "PENDING" || o.status === "IN_PROGRESS");
              const busy = actionId === o.id;
              const isSelected = selected.has(o.id);

              return (
                <li key={o.id} className={cn("rounded-lg border bg-card p-4 transition-shadow hover:shadow-sm", isOverdue && "border-red-300 bg-red-50/30", isSelected && "border-primary ring-1 ring-primary/30")}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        {user.role === "ADMIN" && o.status === "DRAFT" && activeTab !== "OVERDUE" && (
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelect(o.id)}
                            className="h-4 w-4 rounded border-input"
                            aria-label={`Seleccionar ${o.ot_number}`}
                          />
                        )}
                        <span className="font-mono text-sm font-bold text-primary">{o.ot_number}</span>
                        <StatusBadge status={o.status} />
                        {o.submitted_for_review && (
                          <span className="inline-flex items-center rounded-full bg-amber-100 text-amber-800 px-2.5 py-0.5 text-xs font-medium">
                            Pendiente de revisión
                          </span>
                        )}
                        {o.is_planned && (
                          <span className="inline-flex items-center rounded-full bg-purple-100 text-purple-700 px-2.5 py-0.5 text-xs font-medium">
                            Planificada
                          </span>
                        )}
                        {isOverdue && (
                          <span className="inline-flex items-center rounded-full bg-red-100 text-red-700 px-2.5 py-0.5 text-xs font-medium">
                            Vencida
                          </span>
                        )}
                      </div>
                      <div className="mt-1 font-semibold truncate">{o.title || o.equipment_name}</div>
                      <div className="text-sm text-muted-foreground">
                        {o.area_name} · {o.section_name || "-"} · {o.equipment_name || "-"}
                      </div>
                      <div className="mt-0.5 text-sm text-muted-foreground">
                        {maintenanceTypeLabel(o.maintenance_type)} ·{" "}
                        {o.execution_date
                          ? new Date(o.execution_date).toLocaleDateString("es-CL")
                          : "sin fecha"}
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        {o.responsible_user_name ? (
                          <>Responsable: <span className="font-medium text-foreground">{o.responsible_user_name}</span></>
                        ) : (
                          <span className="text-orange-600">Sin responsable asignado</span>
                        )}
                      </div>
                      {o.due_date && (
                        <div className={cn("mt-0.5 text-xs", isOverdue ? "text-red-600 font-semibold" : "text-muted-foreground")}>
                          Fecha límite: {new Date(o.due_date).toLocaleDateString("es-CL")}
                        </div>
                      )}
                      <div className="mt-1.5 flex items-center gap-2 text-xs">
                        <span className="inline-flex items-center gap-1">
                          <span className="text-muted-foreground">OT:</span>
                          <SyncBadge status={o.ot_sheet_sync_status} className="gap-1" />
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <span className="text-muted-foreground">Mensual:</span>
                          <SyncBadge status={o.monthly_sheet_sync_status} className="gap-1" />
                        </span>
                      </div>
                    </div>

                    {/* Action buttons */}
                    <div className="flex flex-col gap-1.5 items-end shrink-0">
                      <Link href={`/ordenes/${o.id}`}>
                        <Button variant="outline" size="sm">
                          <Eye className="mr-1 h-3.5 w-3.5" /> Ver
                        </Button>
                      </Link>
                      {o.status === "DRAFT" && !o.submitted_for_review && (
                        <Link href={`/ordenes/${o.id}?action=issue`}>
                          <Button size="sm">
                            <Send className="mr-1 h-3.5 w-3.5" /> {user.role === "SUPERVISOR" ? "Enviar a revisión" : "Emitir"}
                          </Button>
                        </Link>
                      )}
                      {user.role === "ADMIN" && o.status === "DRAFT" && o.submitted_for_review && (
                        <Link href={`/ordenes/${o.id}`}>
                          <Button size="sm" variant="outline">
                            <Eye className="mr-1 h-3.5 w-3.5" /> Revisar y asignar
                          </Button>
                        </Link>
                      )}
                      {(o.ot_sheet_sync_status === "FAILED" || o.monthly_sheet_sync_status === "FAILED") && (
                        <button
                          onClick={() => retryGoogleSync(o.id)}
                          disabled={busy}
                          className="inline-flex items-center gap-1 text-xs text-red-600 hover:text-red-700 disabled:opacity-50"
                        >
                          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                          Reintentar
                        </button>
                      )}
                      {(o.status === "COMPLETED" || o.status === "APPROVED") && (
                        <button
                          onClick={() => syncMonthly(o.id)}
                          disabled={busy}
                          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary disabled:opacity-50"
                        >
                          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                          Sync mensual
                        </button>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>

          {/* Footer — contador + Cargar más (solo ventana principal) */}
          {activeTab !== "OVERDUE" && (
          <div className="mt-4 flex flex-col items-center gap-3">
            <p className="text-xs text-muted-foreground">
              Mostrando {filtered.length} de {counter ? counter.total_all : filtered.length} OTs
            </p>
            {hasMore && (
              <Button variant="outline" onClick={loadMore} disabled={loadingMore} className="w-full sm:w-auto">
                {loadingMore ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <ChevronDown className="mr-2 h-4 w-4" />
                )}
                Cargar más
              </Button>
            )}
            {!hasMore && orders.length > 0 && (
              <p className="text-xs text-muted-foreground">Fin de la lista</p>
            )}
          </div>
          )}
        </>
      )}
    </Shell>
  );
}
