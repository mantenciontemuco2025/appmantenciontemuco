"use client";

import { Loader2 } from "lucide-react";

export function PageLoading({ message = "Cargando..." }: { message?: string }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="flex flex-col items-center gap-3 text-center text-muted-foreground">
        <Loader2 className="h-8 w-8 animate-spin text-primary" aria-hidden="true" />
        <p className="text-sm">{message}</p>
      </div>
    </main>
  );
}
