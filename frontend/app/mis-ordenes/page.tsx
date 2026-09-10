"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ChevronDown, ClipboardCheck, Loader2, Play, CheckCircle, Eye } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/layout/shell";
import type { WorkOrderListItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { PageLoading } from "@/components/ui/page-loading";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge, maintenanceTypeLabel } from "@/lib/status";
import { cn } from "@/lib/utils";

type TabKey = "PENDING" | "IN_PROGRESS" | "COMPLETED" | "APPROVED";

const TABS: { key: TabKey; label: string }[] = [
  { key: "PENDING", label: "Pendientes" },
  { key: "IN_PROGRESS", label: "En proceso" },
  { key: "COMPLETED", label: "Finalizadas" },
  { key: "APPROVED", label: "Aprobadas" },
];

const PAGE_SIZE = 20;

function tabLabel(status: string): string {
  const map: Record<string, string> = {
    PENDING: "pendiente",
    IN_PROGRESS: "en proceso",
    COMPLETED: "finalizada",
    APPROVED: "aprobada",
  };
  return map[status] || status.toLowerCase();
}

export default function MisOrdenesPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [orders, setOrders] = useState<WorkOrderListItem[]>([]);
  const [loadingOrders, setLoadingOrders] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<TabKey>("PENDING");

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    loadFirstPage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  async function loadFirstPage() {
    setLoadingOrders(true);
    setError("");
    setHasMore(true);
    try {
      // Ventana acotada — nunca una lista infinita. "Cargar más" agrega el
      // siguiente tramo vía offset hasta llegar al final.
      const page = await api.get<WorkOrderListItem[]>(
        `/api/work-orders/my?limit=${PAGE_SIZE}&offset=0`
      );
      setOrders(page);
      setHasMore(page.length === PAGE_SIZE);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al cargar las órdenes");
      setOrders([]);
    } finally {
      setLoadingOrders(false);
    }
  }

  async function loadMore() {
    setLoadingMore(true);
    try {
      const page = await api.get<WorkOrderListItem[]>(
        `/api/work-orders/my?limit=${PAGE_SIZE}&offset=${orders.length}`
      );
      setOrders((prev) => [...prev, ...page]);
      setHasMore(page.length === PAGE_SIZE);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al cargar más órdenes");
    } finally {
      setLoadingMore(false);
    }
  }

  // El filtrado por tab se hace en cliente sobre la ventana cargada.
  const filtered = orders.filter((o) => o.status === activeTab);

  if (loading || !user) {
    return <PageLoading message={loading ? "Validando sesión..." : "Redirigiendo al inicio de sesión..."} />;
  }

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      <div className="mb-5">
        <h1 className="text-2xl font-bold">Mis Órdenes de Trabajo</h1>
        <p className="text-muted-foreground">Órdenes asignadas como responsable o participante</p>
      </div>

      {/* Tabs */}
      <div className="mb-4 flex gap-1 overflow-x-auto border-b">
        {TABS.map((tab) => {
          const count = orders.filter((o) => o.status === tab.key).length;
          return (
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
              {count > 0 && (
                <span className="ml-1.5 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-muted px-1.5 text-xs">
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Order list */}
      {loadingOrders ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
        </div>
      ) : error && filtered.length === 0 ? (
        <EmptyState
          icon={<ClipboardCheck className="h-6 w-6" />}
          title="No se pudieron cargar las órdenes"
          description={error}
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<ClipboardCheck className="h-6 w-6" />}
          title="No hay órdenes en este momento"
          description={`No hay órdenes ${tabLabel(activeTab)} asignadas a usted.`}
        />
      ) : (
        <>
          <ul className="space-y-3">
            {filtered.map((o) => (
              <li key={o.id} className="rounded-lg border bg-card p-4 transition-shadow hover:shadow-sm">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-sm font-bold text-primary">{o.ot_number}</span>
                      <StatusBadge status={o.status} />
                    </div>
                    <div className="mt-1 font-semibold truncate">{o.title || o.equipment_name}</div>
                    <div className="text-sm text-muted-foreground">
                      {o.area_name} · {o.section_name || "-"} · {o.equipment_name || "-"}
                    </div>
                    {o.responsible_user_name && (
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        Responsable: <span className="font-medium text-foreground">{o.responsible_user_name}</span>
                      </div>
                    )}
                    <div className="mt-0.5 text-sm text-muted-foreground">
                      {maintenanceTypeLabel(o.maintenance_type)} ·{" "}
                      {o.execution_date
                        ? new Date(o.execution_date).toLocaleDateString("es-CL")
                        : "sin fecha"}
                    </div>
                    {o.due_date && (
                      <div className={cn(
                        "mt-0.5 text-xs",
                        new Date(o.due_date) < new Date() && (o.status === "PENDING" || o.status === "IN_PROGRESS")
                          ? "text-red-600 font-semibold"
                          : "text-muted-foreground"
                      )}>
                        Fecha límite: {new Date(o.due_date).toLocaleDateString("es-CL")}
                        {new Date(o.due_date) < new Date() && (o.status === "PENDING" || o.status === "IN_PROGRESS") && " (vencida)"}
                      </div>
                    )}
                  </div>

                  {/* Action buttons */}
                  <div className="flex flex-col gap-1.5 items-end shrink-0">
                    <Link href={`/mis-ordenes/${o.id}`}>
                      <Button variant="outline" size="sm">
                        <Eye className="mr-1 h-3.5 w-3.5" /> Ver
                      </Button>
                    </Link>
                    {o.status === "PENDING" && user && o.responsible_user_id === user.id && (
                      <Link href={`/mis-ordenes/${o.id}?action=start`}>
                        <Button size="sm">
                          <Play className="mr-1 h-3.5 w-3.5" /> Iniciar
                        </Button>
                      </Link>
                    )}
                    {o.status === "IN_PROGRESS" && user && o.responsible_user_id === user.id && (
                      <Link href={`/mis-ordenes/${o.id}?action=complete`}>
                        <Button size="sm">
                          <CheckCircle className="mr-1 h-3.5 w-3.5" /> Finalizar
                        </Button>
                      </Link>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>

          {/* Footer — contador + Cargar más */}
          <div className="mt-4 flex flex-col items-center gap-3">
            <p className="text-xs text-muted-foreground">
              Mostrando {filtered.length} órd.{filtered.length === 1 ? "" : "enes"} en esta pestaña
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
        </>
      )}
    </Shell>
  );
}
