"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { MaintenanceWizard } from "@/components/maintenance/maintenance-wizard";
import { Shell } from "@/components/layout/shell";
import { useAuth } from "@/lib/auth";
import { PageLoading } from "@/components/ui/page-loading";

export default function NuevaMantencionPage() {
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
      <h1 className="mb-4 text-xl font-bold">Registrar mantención</h1>
      <MaintenanceWizard />
    </Shell>
  );
}
