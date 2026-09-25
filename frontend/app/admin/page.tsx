"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldAlert, Users, Boxes, Columns3, PackageSearch } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { useAuth } from "@/lib/auth";
import { UserManager } from "@/components/admin/user-manager";
import { AuditLogView } from "@/components/admin/audit-log-view";
import { CatalogManager } from "@/components/admin/catalog-manager";
import { OtCounter } from "@/components/admin/ot-counter";
import { cn } from "@/lib/utils";
import { PageLoading } from "@/components/ui/page-loading";
import { WorkerColumnManager } from "@/components/admin/worker-column-manager";
import { MaterialCatalogManager } from "@/components/admin/material-catalog-manager";

export default function AdminPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<"users" | "audit" | "catalog" | "materials" | "worker-columns">("users");

  useEffect(() => {
    if (!loading && !user) {
      router.push("/login");
    } else if (!loading && user) {
      if (user.role === "WORKER") {
        router.push("/dashboard");
      } else if (user.role === "SUPERVISOR") {
        // Supervisor can only see audit
        setTab("audit");
      }
    }
  }, [loading, user, router]);

  if (loading || !user) {
    return <PageLoading message={loading ? "Validando sesión..." : "Redirigiendo al inicio de sesión..."} />;
  }

  const isAdmin = user.role === "ADMIN";

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      <h1 className="mb-2 text-xl font-bold">Administración</h1>

      {isAdmin && <OtCounter />}

      {isAdmin && (
        <div className="mb-4 flex flex-wrap gap-2">
          <TabButton
            active={tab === "users"}
            onClick={() => setTab("users")}
            icon={<Users className="h-4 w-4" />}
            label="Usuarios"
          />
          <TabButton
            active={tab === "catalog"}
            onClick={() => setTab("catalog")}
            icon={<Boxes className="h-4 w-4" />}
            label="Catálogo"
          />
          <TabButton
            active={tab === "materials"}
            onClick={() => setTab("materials")}
            icon={<PackageSearch className="h-4 w-4" />}
            label="Materiales"
          />
          <TabButton
            active={tab === "audit"}
            onClick={() => setTab("audit")}
            icon={<ShieldAlert className="h-4 w-4" />}
            label="Auditoría"
          />
          <TabButton
            active={tab === "worker-columns"}
            onClick={() => setTab("worker-columns")}
            icon={<Columns3 className="h-4 w-4" />}
            label="Columnas mensuales"
          />
        </div>
      )}

      {tab === "users" && isAdmin && <UserManager />}
      {tab === "catalog" && isAdmin && <CatalogManager />}
      {tab === "materials" && isAdmin && <MaterialCatalogManager />}
      {tab === "worker-columns" && isAdmin && <WorkerColumnManager />}
      {(tab === "audit" || !isAdmin) && <AuditLogView />}
    </Shell>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
        active
          ? "bg-primary text-primary-foreground"
          : "bg-muted text-muted-foreground hover:bg-muted/70"
      )}
    >
      {icon}
      {label}
    </button>
  );
}
