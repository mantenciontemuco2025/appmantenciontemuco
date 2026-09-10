"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { OrderWizard } from "@/components/orders/order-wizard";
import { Shell } from "@/components/layout/shell";
import { useAuth } from "@/lib/auth";
import { PageLoading } from "@/components/ui/page-loading";

export default function NuevaOrdenPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);

  if (loading || !user) {
    return <PageLoading message={loading ? "Validando sesión..." : "Redirigiendo al inicio de sesión..."} />;
  }

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      <div className="mb-4">
        <h1 className="text-xl font-bold">Nueva orden de trabajo</h1>
        <p className="text-sm text-muted-foreground">
          El N° OT se genera automáticamente (OT-2026-NNNN). Los datos quedan en el
          registro mensual y en la plantilla OT.
        </p>
      </div>
      <OrderWizard />
    </Shell>
  );
}
