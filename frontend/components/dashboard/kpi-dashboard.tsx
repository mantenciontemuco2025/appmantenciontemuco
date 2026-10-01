"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  BarChart3,
  CalendarRange,
  CheckCircle2,
  Clock3,
  Filter,
  Gauge,
  ListChecks,
  RefreshCw,
  Users,
  Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import type { KpiResponse } from "@/lib/types";
import { usePlantAreaOptions } from "@/lib/use-plant-area-options";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

const TYPE_LABELS: Record<string, string> = {
  PREVENTIVE: "Preventivo",
  CORRECTIVE: "Correctivo",
  PREDICTIVE: "Predictivo",
  PROYECTO: "Proyecto",
  MONTAJE: "Montaje",
  URGENTE: "Urgente",
};

function localDate(date: Date) {
  const offset = date.getTimezoneOffset();
  return new Date(date.getTime() - offset * 60_000).toISOString().slice(0, 10);
}

const KPI_DATE_RANGE_STORAGE_KEY = "mantencion:kpi-date-range:v1";

function defaultKpiDateRange() {
  const today = new Date();
  return { from: `${today.getFullYear()}-01-01`, to: localDate(today) };
}

function savedKpiDateRange() {
  const fallback = defaultKpiDateRange();
  if (typeof window === "undefined") return fallback;
  try {
    const saved = JSON.parse(window.localStorage.getItem(KPI_DATE_RANGE_STORAGE_KEY) || "null") as { from?: unknown; to?: unknown } | null;
    const validDate = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
    return saved && validDate(saved.from) && validDate(saved.to)
      ? { from: saved.from, to: saved.to }
      : fallback;
  } catch {
    return fallback;
  }
}

function monthLabel(value: string) {
  const [year, month] = value.split("-");
  return new Intl.DateTimeFormat("es-CL", { month: "short" }).format(
    new Date(Number(year), Number(month) - 1, 1),
  ).replace(".", "");
}

function percent(value: number, total: number) {
  return total ? Math.round((value / total) * 100) : 0;
}

function formatHours(value: number) {
  const totalMinutes = Math.max(0, Math.round(value * 60));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return `${minutes} min`;
  if (minutes === 0) return `${hours} h`;
  return `${hours} h ${minutes} min`;
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("es-CL", {
    style: "currency",
    currency: "CLP",
    maximumFractionDigits: 0,
  }).format(Math.max(0, value));
}

function KpiCard({
  label,
  value,
  helper,
  icon,
  tone,
  href,
}: {
  label: string;
  value: string;
  helper: string;
  icon: React.ReactNode;
  tone: string;
  href?: string;
}) {
  return (
    <div
      className={`rounded-2xl border bg-card p-4 shadow-sm transition-shadow hover:shadow-md sm:p-5 ${href ? "cursor-pointer hover:border-primary/50" : ""}`}
      role={href ? "link" : undefined}
      tabIndex={href ? 0 : undefined}
      onClick={() => { if (href) window.location.href = href; }}
      onKeyDown={(event) => { if (href && (event.key === "Enter" || event.key === " ")) window.location.href = href; }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
          <p className="mt-2 text-2xl font-bold tracking-tight sm:text-3xl">{value}</p>
        </div>
        <span className={`rounded-xl p-2.5 ${tone}`}>{icon}</span>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{helper}</p>
    </div>
  );
}

const PIE_COLORS = [
  "#4f86c6", "#c84f4f", "#8064a2", "#f79646", "#7ea6d2",
  "#d78282", "#a9c978", "#a58fbe", "#4fa7a0", "#e1b84b",
];

function DistributionPie({
  title,
  description,
  rows,
  onSegmentClick,
  scrollLegend = false,
}: {
  title: string;
  description: string;
  rows: { label: string; value: number }[];
  onSegmentClick?: (label: string) => void;
  scrollLegend?: boolean;
}) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const data = rows
    .filter((row) => row.value > 0)
    .sort((a, b) => b.value - a.value);
  const total = data.reduce((sum, row) => sum + row.value, 0);
  let cursor = 0;
  const segments = data.map((row, index) => {
    const start = cursor;
    cursor += (row.value / Math.max(total, 1)) * 100;
    return {
      ...row,
      color: PIE_COLORS[index % PIE_COLORS.length],
      start,
      end: cursor,
      percentage: Math.round((row.value / Math.max(total, 1)) * 1000) / 10,
    };
  });

  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border bg-card p-4 shadow-sm sm:p-5">
      <div className="mb-4 text-center">
        <h3 className="text-xl font-semibold">{title}</h3>
        <p className="mt-1 text-xs text-muted-foreground">{description}</p>
      </div>
      {!segments.length ? (
        <div className="flex min-h-64 items-center justify-center text-sm text-muted-foreground">
          No hay datos para este período.
        </div>
      ) : (
        <div className="grid min-w-0 items-center gap-5 md:grid-cols-[minmax(220px,0.9fr)_1.1fr]">
          <div className="flex justify-center">
            <div className="relative aspect-square w-full max-w-[260px]">
              <svg
                viewBox="0 0 200 200"
                className="h-full w-full overflow-visible drop-shadow-sm"
                role="img"
                aria-label={`${title}: ${segments.map((segment) => `${segment.label} ${segment.percentage}%`).join(", ")}`}
                onMouseLeave={() => setHoveredIndex(null)}
              >
                {segments.map((segment, index) => {
                  const startAngle = (segment.start / 100) * 360 - 90;
                  const endAngle = (segment.end / 100) * 360 - 90;
                  const start = {
                    x: 100 + 86 * Math.cos((endAngle * Math.PI) / 180),
                    y: 100 + 86 * Math.sin((endAngle * Math.PI) / 180),
                  };
                  const end = {
                    x: 100 + 86 * Math.cos((startAngle * Math.PI) / 180),
                    y: 100 + 86 * Math.sin((startAngle * Math.PI) / 180),
                  };
                  const largeArc = endAngle - startAngle > 180 ? 1 : 0;
                  const path = [
                    "M 100 100",
                    `L ${start.x} ${start.y}`,
                    `A 86 86 0 ${largeArc} 0 ${end.x} ${end.y}`,
                    "Z",
                  ].join(" ");
                  return (
                    <path
                      key={segment.label}
                      d={path}
                      fill={segment.color}
                      stroke="var(--card)"
                      strokeWidth="1.5"
                      className="cursor-pointer transition-opacity hover:opacity-80"
                      onMouseEnter={() => setHoveredIndex(index)}
                      onClick={() => onSegmentClick?.(segment.label)}
                    />
                  );
                })}
              </svg>
              <div className="pointer-events-none absolute inset-[22%] flex flex-col items-center justify-center rounded-full bg-card text-center shadow-sm">
                {hoveredIndex !== null ? (
                  <>
                    <span className="max-w-[90px] truncate text-xs font-semibold text-foreground">
                      {segments[hoveredIndex].label}
                    </span>
                    <span className="mt-1 text-xl font-bold text-foreground">
                      {segments[hoveredIndex].percentage}%
                    </span>
                    <span className="text-[11px] text-muted-foreground">
                      {segments[hoveredIndex].value} OTs
                    </span>
                  </>
                ) : (
                  <>
                    <span className="text-3xl font-bold text-foreground">{total}</span>
                    <span className="text-xs text-muted-foreground">OTs</span>
                  </>
                )}
              </div>
            </div>
          </div>
          <div className={scrollLegend ? "min-w-0 max-h-64 space-y-2 overflow-y-auto pr-2" : "min-w-0 space-y-2"}>
            {segments.map((segment, index) => (
              <div
                key={segment.label}
                className="flex cursor-pointer items-center gap-2 rounded-md px-1 text-sm transition-colors hover:bg-muted/60"
                onMouseEnter={() => setHoveredIndex(index)}
                onMouseLeave={() => setHoveredIndex(null)}
                onClick={() => onSegmentClick?.(segment.label)}
              >
                <span className="h-3 w-3 shrink-0 rounded-sm" style={{ backgroundColor: segment.color }} />
                <span className="min-w-0 flex-1 truncate" title={segment.label}>{segment.label}</span>
                <span className="font-semibold tabular-nums">{segment.percentage}%</span>
                <span className="w-12 text-right text-xs text-muted-foreground tabular-nums">{segment.value}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function MaterialUsageBars({ rows }: { rows: KpiResponse["by_material"] }) {
  const visibleRows = rows.slice(0, 15);
  const maxValue = Math.max(1, ...visibleRows.map((row) => row.times_used));

  return (
    <div className="rounded-2xl border p-4 sm:p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">Uso de códigos de materiales</h3>
          <p className="text-xs text-muted-foreground">
            Veces que cada código aparece en una OT del período seleccionado
          </p>
        </div>
        <BarChart3 className="h-5 w-5 shrink-0 text-primary" />
      </div>
      {visibleRows.length ? (
        <div className="max-h-96 space-y-3 overflow-y-auto pr-1">
          {visibleRows.map((row) => (
            <div key={row.code} title={`${row.code}${row.description ? ` — ${row.description}` : ""}: ${row.times_used} usos`}>
              <div className="mb-1 flex items-center justify-between gap-3 text-sm">
                <div className="min-w-0">
                  <span className="font-mono font-semibold">{row.code}</span>
                  {row.description ? <span className="ml-2 truncate text-xs text-muted-foreground">{row.description}</span> : null}
                </div>
                <span className="shrink-0 font-semibold tabular-nums text-primary">
                  {row.times_used} {row.times_used === 1 ? "vez" : "veces"}
                </span>
              </div>
              <div className="h-3 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-blue-600 transition-all"
                  style={{ width: `${Math.max(5, (row.times_used / maxValue) * 100)}%` }}
                />
              </div>
              {row.family ? <p className="mt-1 text-[11px] text-muted-foreground">Familia: {row.family}</p> : null}
            </div>
          ))}
        </div>
      ) : (
        <div className="flex min-h-32 items-center justify-center text-sm text-muted-foreground">
          No hay códigos de materiales registrados en este período.
        </div>
      )}
      {rows.length > visibleRows.length ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Se muestran los 15 códigos más utilizados de {rows.length} con registros.
        </p>
      ) : null}
    </div>
  );
}

function KpiProfessionalExtras({ data, ordersHref }: { data: KpiResponse; ordersHref: (filters?: Record<string, string>) => string }) {
  const summary = data.summary;
  // The dashboard can stay open while an API process is being upgraded. Treat
  // fields added by newer API versions as optional during that short window.
  const externalHours = summary.external_hours ?? 0;
  const externalOts = summary.external_ots ?? 0;
  const externalWorkRows = data.by_external_work ?? [];
  const externalCostTotal = summary.external_cost_total ?? 0;
  const externalCostOts = summary.external_cost_ots ?? 0;
  const externalCostMissingOts = summary.external_cost_missing_ots ?? 0;
  const externalCostRows = data.by_external_cost ?? [];
  const draftOts = Math.max(
    0,
    summary.total_ots - summary.completed_ots - summary.pending_ots - summary.in_progress_ots - summary.cancelled_ots,
  );
  const statusRows = [
    { key: "completed", status: "COMPLETED", label: "Finalizadas", count: summary.completed_ots, color: "bg-emerald-600", dot: "bg-emerald-600" },
    { key: "in-progress", status: "IN_PROGRESS", label: "En proceso", count: summary.in_progress_ots, color: "bg-blue-700", dot: "bg-blue-700" },
    { key: "pending", status: "PENDING", label: "Pendientes", count: summary.pending_ots, color: "bg-orange-600", dot: "bg-orange-600" },
    { key: "draft", status: "DRAFT", label: "Borrador", count: draftOts, color: "bg-slate-400", dot: "bg-slate-400" },
    { key: "cancelled", status: "CANCELLED", label: "Canceladas", count: summary.cancelled_ots, color: "bg-background border border-slate-400", dot: "bg-background border border-slate-400" },
  ];
  const statusTotal = Math.max(1, summary.total_ots);

  return (
    <>
      <div className="order-1 mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Horas-persona"
          value={formatHours(summary.total_person_hours)}
          helper="Suma la duración completa para cada participante"
          icon={<Users className="h-5 w-5 text-indigo-700" />}
          tone="bg-indigo-100"
          href={ordersHref()}
        />
        <KpiCard
          label="OTs vencidas"
          value={String(summary.overdue_ots)}
          helper="Pendientes o en proceso con fecha límite pasada"
          icon={<Wrench className="h-5 w-5 text-red-700" />}
          tone="bg-red-100"
          href={ordersHref({ overdue: "true" })}
        />
        <KpiCard
          label="Pendientes antiguas"
          value={String(summary.stale_pending_ots)}
          helper="Pendientes o en proceso de más de 7 días"
          icon={<Clock3 className="h-5 w-5 text-amber-700" />}
          tone="bg-amber-100"
          href={ordersHref({ stale_pending: "true" })}
        />
        <KpiCard
          label="Trabajo externo"
          value={formatHours(externalHours)}
          helper={`${externalOts} OTs; separado de las horas del personal interno`}
          icon={<Users className="h-5 w-5 text-cyan-700" />}
          tone="bg-cyan-100"
          href={ordersHref({ external: "true" })}
        />
        <KpiCard
          label="Gasto externo"
          value={formatCurrency(externalCostTotal)}
          helper={`${externalCostOts} OTs con monto OC · ${externalCostMissingOts} sin monto`}
          icon={<BarChart3 className="h-5 w-5 text-emerald-700" />}
          tone="bg-emerald-100"
          href={ordersHref({ external: "true" })}
        />
      </div>

      <div className="order-2 mt-5 rounded-2xl border p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-semibold">Estado de las {summary.total_ots} OTs</h3>
          <p className="text-sm text-muted-foreground">Distribución del período seleccionado</p>
        </div>
        <div className="flex h-10 overflow-hidden rounded-lg bg-muted/50">
          {statusRows.map((row) => row.count > 0 ? (
            <div
              key={row.key}
              className={`${row.color} cursor-pointer border-r border-card last:border-r-0`}
              style={{ width: `${(row.count / statusTotal) * 100}%` }}
              title={`${row.label}: ${row.count}`}
              aria-label={`${row.label}: ${row.count}`}
              onClick={() => { window.location.href = ordersHref({ status: row.status }); }}
            />
          ) : null)}
        </div>
        <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted-foreground">
          {statusRows.map((row) => <button type="button" key={`legend-${row.key}`} className="inline-flex items-center gap-2 hover:text-primary" onClick={() => { window.location.href = ordersHref({ status: row.status }); }}><span className={`h-3 w-3 rounded-sm ${row.dot}`} />{row.label} <strong className="text-foreground">{row.count}</strong></button>)}
        </div>
      </div>

      <div className="order-5 mt-5 overflow-hidden rounded-2xl border">
        <div className="border-b p-4">
          <h3 className="font-semibold">Trabajos realizados por externos</h3>
          <p className="text-xs text-muted-foreground">Horas y OTs del contratista, sin sumarlas a las horas-persona del administrador.</p>
        </div>
        <div className="max-h-80 overflow-auto">
          <table className="w-full min-w-[700px] text-left text-sm">
            <thead className="sticky top-0 bg-muted/90 text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Persona externa</th>
                <th className="px-4 py-3">Empresa</th>
                <th className="px-4 py-3">Área</th>
                <th className="px-4 py-3">Tipo</th>
                <th className="px-4 py-3 text-right">OTs</th>
                <th className="px-4 py-3 text-right">Finalizadas</th>
                <th className="px-4 py-3 text-right">Horas</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {externalWorkRows.length ? externalWorkRows.map((row) => (
                <tr key={`${row.executor_name}-${row.company || ""}-${row.area_name}-${row.maintenance_type}`}>
                  <td className="px-4 py-3 font-medium">{row.executor_name}</td>
                  <td className="px-4 py-3">{row.company || "—"}</td>
                  <td className="px-4 py-3">{row.area_name}</td>
                  <td className="px-4 py-3">{TYPE_LABELS[row.maintenance_type] || row.maintenance_type}</td>
                  <td className="px-4 py-3 text-right">{row.total_ots}</td>
                  <td className="px-4 py-3 text-right">{row.completed_ots}</td>
                  <td className="px-4 py-3 text-right font-semibold text-primary">{formatHours(row.total_hours)}</td>
                </tr>
              )) : (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">No hay trabajos externos en este período.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="order-5 mt-5 overflow-hidden rounded-2xl border">
        <div className="border-b p-4">
          <h3 className="font-semibold">Gasto de OT externas por empresa</h3>
          <p className="text-xs text-muted-foreground">Suma los montos OC registrados en las OT externas del período.</p>
        </div>
        <div className="space-y-3 p-4">
          {externalCostRows.length ? (() => {
            const maxAmount = Math.max(...externalCostRows.map((row) => row.total_amount), 1);
            return externalCostRows.map((row) => (
              <div key={row.company} className="space-y-1">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="font-medium">{row.company}</span>
                  <span className="whitespace-nowrap font-semibold">{formatCurrency(row.total_amount)}</span>
                </div>
                <div className="h-2.5 overflow-hidden rounded-full bg-muted/60" title={`${row.company}: ${formatCurrency(row.total_amount)}`}>
                  <div className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-500" style={{ width: `${(row.total_amount / maxAmount) * 100}%` }} />
                </div>
                <p className="text-xs text-muted-foreground">{row.ots_with_cost} de {row.total_ots} OT con monto OC</p>
              </div>
            ));
          })() : <p className="py-5 text-center text-sm text-muted-foreground">No hay montos OC registrados en este período.</p>}
        </div>
      </div>

      <div className="order-5 mt-5 overflow-hidden rounded-2xl border">
        <div className="border-b p-4">
          <h3 className="font-semibold">Detalle por trabajador, área y tipo</h3>
          <p className="text-xs text-muted-foreground">Permite identificar combinaciones como Wilson · Cebada · Correctivo · 2 h</p>
        </div>
        <div className="max-h-80 overflow-auto">
          <table className="w-full min-w-[700px] text-left text-sm">
            <thead className="sticky top-0 bg-muted/90 text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Trabajador</th>
                <th className="px-4 py-3">Área</th>
                <th className="px-4 py-3">Tipo</th>
                <th className="px-4 py-3 text-right">OTs</th>
                <th className="px-4 py-3 text-right">Finalizadas</th>
                <th className="px-4 py-3 text-right">Horas-persona</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data.by_worker_detail.length ? data.by_worker_detail.map((row) => (
                <tr key={`${row.user_id}-${row.area_name}-${row.maintenance_type}`}>
                  <td className="px-4 py-3 font-medium">{row.worker_name}</td>
                  <td className="px-4 py-3">{row.area_name}</td>
                  <td className="px-4 py-3">{TYPE_LABELS[row.maintenance_type] || row.maintenance_type}</td>
                  <td className="px-4 py-3 text-right">{row.assigned_ots}</td>
                  <td className="px-4 py-3 text-right">{row.completed_ots}</td>
                  <td className="px-4 py-3 text-right font-semibold text-primary">{formatHours(row.person_hours)}</td>
                </tr>
              )) : <tr><td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">No hay detalle de participantes en el período.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="order-5 mt-5 overflow-hidden rounded-2xl border">
        <div className="border-b p-4">
          <h3 className="font-semibold">Distribución por área y tipo</h3>
          <p className="text-xs text-muted-foreground">Las horas de esta tabla cuentan cada OT una sola vez</p>
        </div>
        <div className="max-h-72 overflow-auto">
          <table className="w-full min-w-[520px] text-left text-sm">
            <thead className="sticky top-0 bg-muted/90 text-xs uppercase text-muted-foreground">
              <tr><th className="px-4 py-3">Área</th><th className="px-4 py-3">Tipo</th><th className="px-4 py-3 text-right">OTs</th><th className="px-4 py-3 text-right">Finalizadas</th><th className="px-4 py-3 text-right">Horas OT</th></tr>
            </thead>
            <tbody className="divide-y">
              {data.by_area_type.length ? data.by_area_type.map((row) => (
                <tr key={`${row.area_name}-${row.maintenance_type}`}>
                  <td className="px-4 py-3 font-medium">{row.area_name}</td>
                  <td className="px-4 py-3">{TYPE_LABELS[row.maintenance_type] || row.maintenance_type}</td>
                  <td className="px-4 py-3 text-right">{row.total_ots}</td>
                  <td className="px-4 py-3 text-right">{row.completed_ots}</td>
                  <td className="px-4 py-3 text-right font-semibold">{formatHours(row.total_hours)}</td>
                </tr>
              )) : <tr><td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">No hay datos por área en el período.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <p className="order-6 mt-4 text-right text-xs text-muted-foreground">
        Período: {new Date(data.date_from).toLocaleDateString("es-CL")} — {new Date(data.date_to).toLocaleDateString("es-CL")} · Actualizado: {new Date(data.generated_at).toLocaleString("es-CL")}
      </p>
    </>
  );
}

export function KpiDashboard() {
  const plantAreaOptions = usePlantAreaOptions();
  const initialDates = defaultKpiDateRange();
  const [dateFrom, setDateFrom] = useState(initialDates.from);
  const [dateTo, setDateTo] = useState(initialDates.to);
  const [datesHydrated, setDatesHydrated] = useState(false);
  const [plantArea, setPlantArea] = useState("");
  const [maintenanceType, setMaintenanceType] = useState("");
  const [data, setData] = useState<KpiResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const saved = savedKpiDateRange();
    setDateFrom(saved.from);
    setDateTo(saved.to);
    setDatesHydrated(true);
  }, []);

  useEffect(() => {
    if (!datesHydrated) return;
    try {
      window.localStorage.setItem(
        KPI_DATE_RANGE_STORAGE_KEY,
        JSON.stringify({ from: dateFrom, to: dateTo }),
      );
    } catch {
      // La persistencia local es opcional; el informe sigue funcionando si el
      // navegador bloquea el almacenamiento.
    }
  }, [dateFrom, dateTo, datesHydrated]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo });
    if (plantArea) params.set("plant_area", plantArea);
    if (maintenanceType) params.set("maintenance_type", maintenanceType);
    try {
      setData(await api.get<KpiResponse>(`/api/kpis?${params.toString()}`));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudieron cargar los KPI");
    } finally {
      setLoading(false);
    }
  }, [plantArea, dateFrom, dateTo, maintenanceType]);

  useEffect(() => {
    if (datesHydrated) void load();
  }, [datesHydrated, load]);

  const maxType = Math.max(1, ...(data?.by_maintenance_type.map((row) => row.total_ots) || [1]));
  const maxPlannedMonth = Math.max(1, ...(data?.by_month.map((row) => row.planned_ots) || [1]));
  const summary = data?.summary;
  const missingAreaRow = data?.by_area.find((row) => row.area_name === "Sin área");
  function ordersHref(filters: Record<string, string> = {}) {
    if (!data) return "/ordenes";
    const params = new URLSearchParams({ date_from: data.date_from, date_to: data.date_to });
    if (plantArea && !("plant_area" in filters) && !("without_area" in filters)) params.set("plant_area", plantArea);
    if (maintenanceType && !("maintenance_type" in filters)) params.set("maintenance_type", maintenanceType);
    Object.entries(filters).forEach(([key, value]) => params.set(key, value));
    if (filters.without_area === "true") params.delete("plant_area");
    return `/ordenes?${params.toString()}`;
  }
  const sectionDistribution = useMemo(() => {
    const totals = new Map<string, number>();
    for (const row of data?.by_section ?? []) {
      totals.set(row.section_name, (totals.get(row.section_name) ?? 0) + row.total_ots);
    }
    return Array.from(totals, ([label, value]) => ({ label, value }));
  }, [data?.by_section]);

  return (
    <section className="mb-8 overflow-hidden rounded-3xl border bg-card shadow-sm">
      <div className="bg-gradient-to-br from-slate-950 via-blue-950 to-indigo-900 px-5 py-6 text-white sm:px-7">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2 text-blue-200">
              <Gauge className="h-5 w-5" />
              <span className="text-sm font-semibold uppercase tracking-[0.18em]">Gestión operacional</span>
            </div>
            <h2 className="text-2xl font-bold sm:text-3xl">Indicadores de mantenimiento</h2>
            <p className="mt-1 max-w-2xl text-sm text-blue-100/80">Resumen de OTs, horas y cumplimiento del período seleccionado.</p>
          </div>
          <div className="rounded-xl bg-white/10 px-3 py-2 text-xs text-blue-100 backdrop-blur-sm">
            Las horas de una OT se asignan completas a cada participante.
          </div>
        </div>
      </div>

      <div className="border-b bg-muted/20 p-4 sm:p-5">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><Filter className="h-4 w-4 text-primary" /> Filtros del informe</div>
        <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" onSubmit={(event) => { event.preventDefault(); void load(); }}>
          <Input aria-label="Desde" type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
          <Input aria-label="Hasta" type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
          <Select aria-label="Área" value={plantArea} onChange={(event) => setPlantArea(event.target.value)} options={plantAreaOptions.map((area) => ({ value: area.name, label: area.name }))} placeholder="Todas las áreas" />
          <Select aria-label="Tipo" value={maintenanceType} onChange={(event) => setMaintenanceType(event.target.value)} options={Object.entries(TYPE_LABELS).map(([value, label]) => ({ value, label }))} placeholder="Todos los tipos" />
          <Button type="submit" disabled={loading} className="h-12 gap-2"><RefreshCw className={loading ? "h-4 w-4 animate-spin" : "h-4 w-4"} /> Actualizar</Button>
        </form>
      </div>

      <div className="flex flex-col p-4 sm:p-6">
        {error ? (
          <div className="mb-5 rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">{error}. Revisa la sesión y vuelve a actualizar.</div>
        ) : null}
        {loading && !data ? (
          <div className="flex min-h-48 items-center justify-center text-muted-foreground"><RefreshCw className="mr-2 h-5 w-5 animate-spin" /> Cargando indicadores...</div>
        ) : summary ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
              <KpiCard label="OTs totales" value={String(summary.total_ots)} helper={`${formatHours(summary.average_hours_per_ot)} promedio por OT`} icon={<ListChecks className="h-5 w-5 text-blue-700" />} tone="bg-blue-100" href={ordersHref()} />
              <KpiCard label="Horas acumuladas" value={formatHours(summary.total_hours)} helper="Horas registradas por OT" icon={<Clock3 className="h-5 w-5 text-violet-700" />} tone="bg-violet-100" href={ordersHref()} />
              <KpiCard label="Finalizadas" value={String(summary.completed_ots)} helper="Completadas o aprobadas" icon={<CheckCircle2 className="h-5 w-5 text-green-700" />} tone="bg-green-100" href={ordersHref({ status: "COMPLETED" })} />
              <KpiCard label="Pendientes" value={String(summary.pending_ots)} helper="Esperando ejecución" icon={<CalendarRange className="h-5 w-5 text-amber-700" />} tone="bg-amber-100" href={ordersHref({ status: "PENDING" })} />
              <KpiCard label="En proceso" value={String(summary.in_progress_ots)} helper={`${summary.cancelled_ots} canceladas`} icon={<Wrench className="h-5 w-5 text-orange-700" />} tone="bg-orange-100" href={ordersHref({ status: "IN_PROGRESS" })} />
            </div>

            <KpiProfessionalExtras data={data} ordersHref={ordersHref} />

            <div className="order-3 mt-5 grid gap-5 lg:grid-cols-2">
              <DistributionPie
                title="Recuento de áreas"
                description="Distribución de las OTs del período por área"
                rows={data.by_area.map((row) => ({ label: row.area_name, value: row.total_ots }))}
                onSegmentClick={(label) => {
                  window.location.href = ordersHref(label === "Sin área" ? { without_area: "true" } : { plant_area: label });
                }}
              />
              <DistributionPie
                title="Participaciones por trabajador"
                description="Cada participación de una OT por responsable"
                rows={data.by_worker.map((row) => ({ label: row.worker_name, value: row.assigned_ots }))}
                onSegmentClick={(label) => { window.location.href = ordersHref({ responsible: label }); }}
              />
              <div className="lg:col-span-2">
                <DistributionPie
                  title="Recuento de secciones"
                  description="Distribución de las OTs por sección"
                  rows={sectionDistribution}
                  scrollLegend
                  onSegmentClick={(label) => { window.location.href = ordersHref(label === "Sin sección" ? { without_section: "true" } : { section_name: label }); }}
                />
              </div>
            </div>

            <div className="order-4 mt-5">
              <MaterialUsageBars rows={data.by_material ?? []} />
            </div>

            <div className="order-5 mt-5 grid gap-5 lg:grid-cols-2">
              <div className="rounded-2xl border p-4 sm:p-5">
                <div className="mb-4 flex items-center justify-between"><div><h3 className="font-semibold">Por tipo de mantenimiento</h3><p className="text-xs text-muted-foreground">Cantidad de OTs y horas</p></div><BarChart3 className="h-5 w-5 text-primary" /></div>
                <div className="space-y-4">
                  {data.by_maintenance_type.length ? data.by_maintenance_type.map((row) => <button type="button" key={row.maintenance_type} className="block w-full cursor-pointer text-left" onClick={() => { window.location.href = ordersHref({ maintenance_type: row.maintenance_type }); }}><div className="mb-1 flex justify-between text-sm"><span className="font-medium">{TYPE_LABELS[row.maintenance_type] || row.maintenance_type}</span><span className="text-muted-foreground">{row.total_ots} OTs · {formatHours(row.total_hours)}</span></div><div className="h-2.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-gradient-to-r from-blue-600 to-indigo-500 transition-opacity hover:opacity-80" style={{ width: `${(row.total_ots / maxType) * 100}%` }} /></div></button>) : <p className="py-5 text-center text-sm text-muted-foreground">No hay datos para este período.</p>}
                </div>
              </div>
              <div className="rounded-2xl border p-4 sm:p-5">
                <div className="mb-4 flex items-center justify-between"><div><h3 className="font-semibold">Cumplimiento mensual</h3><p className="text-xs text-muted-foreground">OTs planificadas, ejecutadas y horas por mes</p></div><CalendarRange className="h-5 w-5 text-primary" /></div>
                <div className="mb-3 flex flex-wrap gap-3 text-[10px] text-muted-foreground"><span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-blue-500" />Planificadas</span><span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-emerald-500" />Ejecutadas</span><span className="text-muted-foreground">Pasa el mouse sobre una barra para ver su valor.</span></div>
                <div className="flex min-h-36 items-end gap-2 overflow-x-auto pb-1">
                  {data.by_month.length ? data.by_month.map((row) => <div key={row.month} className="flex min-w-20 flex-1 flex-col items-center gap-1"><span className="text-xs font-semibold text-primary">{row.compliance_percent === null ? "—" : `${row.compliance_percent}%`}</span><div className="flex h-24 w-full items-end justify-center gap-1 rounded-t-md bg-muted/50 px-2"><div title={`Planificadas: ${row.planned_ots}`} className="w-1/2 rounded-t-md bg-blue-500/80" style={{ height: row.planned_ots ? `${Math.max(8, (row.planned_ots / maxPlannedMonth) * 100)}%` : "0%" }} /><div title={`Ejecutadas: ${row.executed_planned_ots}`} className="w-1/2 rounded-t-md bg-emerald-500/80" style={{ height: row.planned_ots && row.executed_planned_ots ? `${Math.max(8, (row.executed_planned_ots / maxPlannedMonth) * 100)}%` : "0%" }} /></div><span className="text-xs font-medium capitalize">{monthLabel(row.month)}</span><span className="text-[10px] text-muted-foreground">{row.executed_planned_ots}/{row.planned_ots} ejecutadas</span><span className="text-[10px] text-muted-foreground">{formatHours(row.total_hours)} · {row.total_ots} OTs</span></div>) : <p className="m-auto text-sm text-muted-foreground">No hay datos para este período.</p>}
                </div>
              </div>
            </div>

            <div className="order-6 mt-5 grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
              <div className="overflow-hidden rounded-2xl border"><div className="flex items-center justify-between border-b p-4"><div><h3 className="font-semibold">Horas por trabajador</h3><p className="text-xs text-muted-foreground">Cada participante recibe la duración completa de la OT</p></div><Users className="h-5 w-5 text-primary" /></div><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-muted/40 text-xs uppercase text-muted-foreground"><tr><th className="px-4 py-3">Trabajador</th><th className="px-4 py-3 text-right">OTs</th><th className="px-4 py-3 text-right">Finalizadas</th><th className="px-4 py-3 text-right">Horas</th></tr></thead><tbody className="divide-y">{data.by_worker.length ? data.by_worker.map((row) => <tr key={row.user_id} className="cursor-pointer hover:bg-muted/40" role="link" tabIndex={0} onClick={() => { window.location.href = ordersHref({ responsible: row.worker_name }); }} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") window.location.href = ordersHref({ responsible: row.worker_name }); }}><td className="px-4 py-3 font-medium">{row.worker_name}</td><td className="px-4 py-3 text-right">{row.assigned_ots}</td><td className="px-4 py-3 text-right">{row.completed_ots} <span className="text-xs text-muted-foreground">({percent(row.completed_ots, row.assigned_ots)}%)</span></td><td className="px-4 py-3 text-right font-semibold text-primary">{formatHours(row.total_hours)}</td></tr>) : <tr><td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">No hay participantes en el período.</td></tr>}</tbody></table></div></div>
              <div className="overflow-hidden rounded-2xl border">
                <div className="flex items-center justify-between border-b p-4">
                  <div><h3 className="font-semibold">Por área</h3><p className="text-xs text-muted-foreground">Preventivo y correctivo por área</p></div>
                  <Wrench className="h-5 w-5 text-primary" />
                </div>
                {missingAreaRow ? <div className="border-b bg-amber-50 px-4 py-3 text-sm text-amber-900"><span>Hay <strong>{missingAreaRow.total_ots}</strong> OTs sin área general.</span>{" "}<Link href={ordersHref({ without_area: "true" })} className="font-semibold underline underline-offset-2 hover:text-amber-700">Ver y clasificar</Link></div> : null}
                <div className="max-h-80 overflow-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="sticky top-0 bg-muted/90 text-xs uppercase text-muted-foreground"><tr><th className="px-4 py-3">Área</th><th className="px-4 py-3 text-right">OTs</th><th className="px-4 py-3 text-right">Horas</th></tr></thead>
                    <tbody className="divide-y">
                      {data.by_area.length ? data.by_area.map((row) => {
                        const missingArea = row.area_name === "Sin área";
                        const cells = <><td className="px-4 py-3"><div className="font-medium">{row.area_name}</div><div className="text-xs text-muted-foreground">P {row.preventive_ots} · C {row.corrective_ots}</div></td><td className="px-4 py-3 text-right">{row.total_ots}</td><td className="px-4 py-3 text-right font-semibold">{formatHours(row.total_hours)}</td></>;
                        const destination = missingArea ? ordersHref({ without_area: "true" }) : ordersHref({ plant_area: row.area_name });
                        return <tr key={row.area_name} className={`cursor-pointer hover:bg-muted/40 ${missingArea ? "bg-amber-50/60 hover:bg-amber-100/70" : ""}`} role="link" tabIndex={0} onClick={() => { window.location.href = destination; }} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") window.location.href = destination; }}>{cells}</tr>;
                      }) : <tr><td colSpan={3} className="px-4 py-8 text-center text-muted-foreground">No hay áreas en el período.</td></tr>}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </section>
  );
}
