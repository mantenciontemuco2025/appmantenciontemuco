"use client";

import { useEffect, useState } from "react";
import { Hash, CalendarRange, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { WorkOrderCounter } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";

const MONTH_NAMES = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
];

export function OtCounter() {
  const [counter, setCounter] = useState<WorkOrderCounter | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<WorkOrderCounter>("/api/work-orders/counter")
      .then(setCounter)
      .catch(() => setError("No se pudo cargar el contador de OTs"));
  }, []);

  if (error) return <Card><CardContent className="p-4 text-sm text-destructive">{error}</CardContent></Card>;
  if (!counter) {
    return (
      <Card className="animate-pulse">
        <CardContent className="h-24 p-4 flex items-center gap-2 text-sm text-muted-foreground">
          <Hash className="h-4 w-4" /> Cargando contador de OTs...
        </CardContent>
      </Card>
    );
  }

  const monthTotals = Object.entries(counter.per_month).sort(
    ([a], [b]) => Number(a) - Number(b)
  );

  return (
    <Card className="mb-4">
      <CardContent className="p-4">
        <div className="mb-3 flex items-center gap-2">
          <Hash className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">Contador de OTs</h3>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-lg border bg-muted/40 p-3">
            <div className="text-xs text-muted-foreground">Total de OTs (todos los años)</div>
            <div className="mt-1 text-2xl font-bold">{counter.total_all}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              {Object.entries(counter.per_year)
                .sort(([a], [b]) => Number(b) - Number(a))
                .map(([y, t]) => `${y}: ${t}`)
                .join(" · ")}
            </div>
          </div>

          <div className="rounded-lg border bg-muted/40 p-3">
            <div className="text-xs text-muted-foreground">Próximo N° OT</div>
            <div className="mt-1 font-mono text-2xl font-bold text-primary">
              {counter.next_ot_number}
            </div>
            <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
              <CalendarRange className="h-3 w-3" /> Se asigna al crear la siguiente OT
            </div>
          </div>

          <div className="rounded-lg border bg-muted/40 p-3">
            <div className="text-xs text-muted-foreground">OT en {counter.current_year} por mes</div>
            <div className="mt-1 grid grid-cols-4 gap-x-2 gap-y-1 lg:grid-cols-6">
              {monthTotals.map(([m, t]) => (
                <div key={m} className="flex flex-col items-center rounded bg-background px-1 py-1">
                  <span className="text-[10px] leading-none text-muted-foreground">{MONTH_NAMES[Number(m)].slice(0, 3)}</span>
                  <span className="text-sm font-semibold">{t}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
          <Sparkles className="h-3 w-3" /> Basado en la fecha de ejecución
        </div>
      </CardContent>
    </Card>
  );
}