"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Shell } from "@/components/layout/shell";
import { HallazgoWizard } from "@/components/orders/hallazgo-wizard";
import { useAuth } from "@/lib/auth";
import { PageLoading } from "@/components/ui/page-loading";

export default function NuevoHallazgoPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (loading) return;
    if (!user) router.push("/login");
    else if (user.role === "ADMIN") router.replace("/hallazgos");
    else if (user.role === "SUPERVISOR") router.replace("/dashboard");
  }, [loading, user, router]);
  if (loading || !user) return <PageLoading message="Validando sesión..." />;
  return <Shell fullName={user.full_name} role={user.role} onLogout={logout}><div className="mb-4"><h1 className="text-xl font-bold">Reportar hallazgo o trabajo realizado</h1><p className="text-sm text-muted-foreground">El administrador revisará el registro y, si corresponde, lo convertirá en una OT planificada.</p></div><HallazgoWizard /></Shell>;
}
