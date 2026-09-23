"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus, RefreshCw } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { PageLoading } from "@/components/ui/page-loading";
import { Button } from "@/components/ui/button";
import type { WorkOrderListItem } from "@/lib/types";

const STATUS_STYLES: Record<string, { label: string; badge: string; border: string }> = {
  PENDING_REVIEW: {
    label: "Pendiente de revisión",
    badge: "border-amber-200 bg-amber-100 text-amber-900",
    border: "border-amber-200",
  },
  RETURNED: {
    label: "Devuelto para corregir",
    badge: "border-orange-200 bg-orange-100 text-orange-900",
    border: "border-orange-200",
  },
  REJECTED: {
    label: "Rechazado",
    badge: "border-red-200 bg-red-100 text-red-900",
    border: "border-red-200",
  },
  CONVERTED: {
    label: "Convertido a OT",
    badge: "border-emerald-200 bg-emerald-100 text-emerald-900",
    border: "border-emerald-200",
  },
};

function statusStyle(status: string | null | undefined) {
  return STATUS_STYLES[status || ""] || {
    label: status || "Sin estado",
    badge: "border-slate-200 bg-slate-100 text-slate-800",
    border: "border-slate-200",
  };
}

type HallazgoFilter = "PENDING" | "IN_PROGRESS" | "COMPLETED" | "APPROVED" | "REJECTED";

const FILTERS: { key: HallazgoFilter; label: string }[] = [
  { key: "PENDING", label: "Pendientes" },
  { key: "IN_PROGRESS", label: "En proceso" },
  { key: "COMPLETED", label: "Finalizadas" },
  { key: "APPROVED", label: "Aprobadas" },
  { key: "REJECTED", label: "Rechazadas" },
];

function filterFor(item: WorkOrderListItem): HallazgoFilter {
  if (item.hallazgo_status === "REJECTED") return "REJECTED";
  if (item.hallazgo_status !== "CONVERTED") return "PENDING";
  if (item.status === "APPROVED") return "APPROVED";
  if (item.status === "COMPLETED") return "COMPLETED";
  return "IN_PROGRESS";
}

export default function HallazgosPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [items, setItems] = useState<WorkOrderListItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<HallazgoFilter>("PENDING");

  async function load() {
    setBusy(true);
    setError("");
    try {
      setItems(await api.get<WorkOrderListItem[]>("/api/work-orders/hallazgos"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron cargar los hallazgos");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!user) return;
    if (user.role === "SUPERVISOR") {
      router.replace("/dashboard");
      return;
    }
    load();
  }, [user, router]);

  if (loading || !user) return <PageLoading message="Validando sesión..." />;

  const counts = FILTERS.reduce<Record<HallazgoFilter, number>>((result, option) => {
    result[option.key] = items.filter((item) => filterFor(item) === option.key).length;
    return result;
  }, { PENDING: 0, IN_PROGRESS: 0, COMPLETED: 0, APPROVED: 0, REJECTED: 0 });
  const visibleItems = items.filter((item) => filterFor(item) === filter);

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      <div className="mb-5 flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">Hallazgos y trabajos abiertos</h1>
          <p className="text-sm text-muted-foreground">Registros provisionales antes de convertirse en una OT oficial.</p>
        </div>
        {user.role === "WORKER" && (
          <Link href="/hallazgos/nuevo">
            <Button><Plus className="mr-1 h-4 w-4" />Nuevo hallazgo</Button>
          </Link>
        )}
      </div>

      {error && <p className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <div className="mb-5 overflow-x-auto border-b" role="tablist" aria-label="Filtrar hallazgos por estado">
        <div className="flex min-w-max gap-6">
          {FILTERS.map((option) => {
            const active = filter === option.key;
            return (
              <button
                key={option.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setFilter(option.key)}
                className={`border-b-2 px-1 pb-3 text-base transition-colors ${active ? "border-blue-600 font-semibold text-blue-600" : "border-transparent text-muted-foreground hover:border-slate-300 hover:text-foreground"}`}
              >
                {option.label}
                <span className={`ml-2 rounded-full px-2 py-0.5 text-xs ${active ? "bg-blue-50 text-blue-700" : "bg-muted text-muted-foreground"}`}>{counts[option.key]}</span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="mb-3 flex justify-end">
        <Button variant="outline" size="sm" onClick={load} disabled={busy}>
          <RefreshCw className={`mr-1 h-4 w-4 ${busy ? "animate-spin" : ""}`} />Actualizar
        </Button>
      </div>

      <div className="space-y-3">
        {visibleItems.map((item) => {
          const style = statusStyle(item.hallazgo_status);
          return (
            <Link key={item.id} href={`/ordenes/${item.id}`} className={`block rounded-xl border bg-card p-4 transition hover:shadow-sm ${style.border}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono font-semibold text-primary">{item.hallazgo_folio || item.ot_number}</span>
                <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${style.badge}`}>{style.label}</span>
              </div>
              <div className="mt-1 font-semibold">{item.title}</div>
              <div className="mt-1 text-sm text-muted-foreground">{item.plant_area} · {item.section_name || "Sin sección"} · {item.equipment_name || "Sin equipo"}</div>
              <div className="mt-2 text-xs text-muted-foreground">
                {item.hallazgo_kind === "COMPLETED" ? "Trabajo ya realizado" : "Requiere atención"}
                {item.hallazgo_priority && ` · Prioridad ${item.hallazgo_priority.toLowerCase()}`}
              </div>
            </Link>
          );
        })}
        {!visibleItems.length && !busy && <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">No hay hallazgos en este estado.</div>}
      </div>
    </Shell>
  );
}
