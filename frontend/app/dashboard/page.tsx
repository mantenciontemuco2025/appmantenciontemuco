"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus, Loader2, ClipboardList, ClipboardCheck } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import type { WorkOrderListItem } from "@/lib/types";
import { StatusBadge } from "@/lib/status";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { PageLoading } from "@/components/ui/page-loading";
import { KpiDashboard } from "@/components/dashboard/kpi-dashboard";

export default function DashboardPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [orders, setOrders] = useState<WorkOrderListItem[]>([]);
  const [loadingOrders, setLoadingOrders] = useState(true);

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    const endpoint =
      user.role === "ADMIN" || user.role === "SUPERVISOR"
        ? "/api/work-orders?limit=5"
        : "/api/work-orders/my?limit=5";
    api
      .get<WorkOrderListItem[]>(endpoint)
      .then(setOrders)
      .catch(() => setOrders([]))
      .finally(() => setLoadingOrders(false));
  }, [user]);

  if (loading || !user) {
    return <PageLoading message={loading ? "Validando sesión..." : "Redirigiendo al inicio de sesión..."} />;
  }

  const isAdmin = user.role === "ADMIN";
  const isManager = isAdmin || user.role === "SUPERVISOR";

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      <div className="mb-5">
        <h1 className="text-2xl font-bold">Hola, {user.full_name || user.email}</h1>
        <p className="text-muted-foreground">
          {isManager
            ? "Registre y dé seguimiento a sus órdenes de trabajo"
            : "Consulte y ejecute sus órdenes de trabajo asignadas"}
        </p>
      </div>

      {/* Acciones principales — grid en desktop, una columna en celular */}
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Link href="/mis-ordenes">
          <div className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary p-4 text-lg font-semibold text-primary-foreground shadow transition-opacity hover:opacity-95">
            <ClipboardCheck className="h-5 w-5" />
            Mis Órdenes
          </div>
        </Link>

        {isManager && (
          <>
            <Link href="/ordenes/nuevo">
              <div className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary/90 p-4 text-lg font-semibold text-primary-foreground shadow transition-opacity hover:opacity-95">
                <Plus className="h-5 w-5" />
                Nueva OT
              </div>
            </Link>
            <Link href="/ordenes">
              <div className="flex w-full items-center justify-center gap-2 rounded-xl bg-muted p-4 text-lg font-semibold shadow transition-colors hover:bg-muted/80">
                <ClipboardList className="h-5 w-5" />
                Órdenes (OT)
              </div>
            </Link>
          </>
        )}
      </div>

      {isManager && <KpiDashboard />}

      <section>
        <h2 className="mb-3 text-lg font-semibold">
          {isManager ? "Órdenes recientes" : "Mis órdenes recientes"}
        </h2>
        {loadingOrders ? (
          <div className="flex justify-center py-10">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : orders.length === 0 ? (
          <EmptyState
            icon={<ClipboardList className="h-6 w-6" />}
            title="Aún no hay órdenes de trabajo"
            description={
              isManager
                ? "Toque “Nueva OT” para registrar su primera orden."
                : "Cuando le asignen una orden de trabajo, aparecerá aquí."
            }
            action={
              isManager ? (
                <Link href="/ordenes/nuevo">
                  <Button size="sm">
                    <Plus className="mr-1 h-4 w-4" /> Nueva OT
                  </Button>
                </Link>
              ) : undefined
            }
          />
        ) : (
          <ul className="space-y-2">
            {orders.map((o) => (
              <li key={o.id}>
                <Link
                  href={`/mis-ordenes/${o.id}`}
                  className="block rounded-lg border bg-card p-4 transition-shadow hover:shadow-sm"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="font-mono text-sm font-bold text-primary truncate">
                        {o.ot_number}
                      </span>
                      <StatusBadge status={o.status} />
                    </div>
                    {o.responsible_user_name && (
                      <span className="text-xs text-muted-foreground shrink-0">
                        {o.responsible_user_name}
                      </span>
                    )}
                  </div>
                  <div className="mt-1 font-medium truncate">{o.title || o.equipment_name}</div>
                  <div className="text-sm text-muted-foreground">
                    {o.area_name} · {o.section_name || "-"} · {o.equipment_name || "-"}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </Shell>
  );
}
