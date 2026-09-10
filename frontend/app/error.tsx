"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Error de renderizado en la aplicación", error);
  }, [error]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4">
      <section className="w-full max-w-md rounded-xl border bg-card p-6 text-center shadow-sm">
        <AlertTriangle className="mx-auto mb-3 h-10 w-10 text-destructive" aria-hidden="true" />
        <h1 className="text-lg font-semibold">No pudimos cargar esta pantalla</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          El resto de la aplicación sigue disponible. Puedes reintentar sin perder los datos guardados.
        </p>
        <Button className="mt-5" onClick={() => reset()}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Reintentar
        </Button>
      </section>
    </main>
  );
}
