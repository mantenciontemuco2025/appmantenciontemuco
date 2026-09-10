"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Wrench, LayoutDashboard, ClipboardList, ClipboardCheck, Users, LogOut, PenLine } from "lucide-react";
import { cn } from "@/lib/utils";
import { NotificationBell } from "@/components/notifications/bell";

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
  adminOnly?: boolean;
  managerOnly?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: <LayoutDashboard className="h-4 w-4" /> },
  { href: "/mis-ordenes", label: "Mis Órdenes", icon: <ClipboardCheck className="h-4 w-4" /> },
  { href: "/ordenes", label: "Órdenes", icon: <ClipboardList className="h-4 w-4" />, managerOnly: true },
  { href: "/perfil", label: "Mi perfil", icon: <PenLine className="h-4 w-4" /> },
  { href: "/admin", label: "Admin", icon: <Users className="h-4 w-4" />, adminOnly: true },
];

export function Shell({
  children,
  fullName,
  role,
  onLogout,
}: {
  children: React.ReactNode;
  fullName: string;
  role: string;
  onLogout: () => void;
}) {
  const pathname = usePathname();

  function isActive(item: NavItem): boolean {
    // Los enlaces con sub-rutas (detalles, creación) cuentan como activos en su
    // sección: /ordenes activa /ordenes/:id y /ordenes/nuevo.
    if (pathname === item.href) return true;
    if (pathname.startsWith(item.href + "/")) return true;
    return false;
  }

  const roleLabel = role === "ADMIN" ? "Administrador" : role === "SUPERVISOR" ? "Supervisor" : "Trabajador";

  return (
    <div className="min-h-screen flex flex-col bg-background">
      {/* ── Header ─────────────────────────────────────────────── */}
      <header className="border-b bg-card sticky top-0 z-10">
        <div className="mx-auto w-full max-w-6xl px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <Wrench className="h-5 w-5" />
            </span>
            <div>
              <div className="font-semibold leading-tight flex items-center gap-1.5">
                Órdenes de Trabajo
              </div>
              <div className="text-xs text-muted-foreground truncate max-w-[50vw] sm:max-w-none">
                Hola, {fullName || "..."}
                <span className="hidden sm:inline"> · {roleLabel}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <NotificationBell />
            <button
              onClick={onLogout}
              className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              aria-label="Cerrar sesión"
            >
              <LogOut className="h-4 w-4" />
              <span className="hidden sm:inline">Salir</span>
            </button>
          </div>
        </div>
      </header>

      {/* ── Nav ────────────────────────────────────────────────── */}
      <nav className="border-b bg-card">
        <div className="mx-auto w-full max-w-6xl px-4">
          <div className="flex items-center gap-1 overflow-x-auto md:flex-wrap">
            {NAV_ITEMS.filter(
              (item) =>
                (!item.adminOnly || role === "ADMIN") &&
                (!item.managerOnly || role === "ADMIN" || role === "SUPERVISOR")
            ).map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "inline-flex items-center gap-1.5 px-3 py-3 text-sm font-medium whitespace-nowrap border-b-2 transition-colors shrink-0",
                  isActive(item)
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
              >
                {item.icon}
                {item.label}
              </Link>
            ))}
          </div>
        </div>
      </nav>

      {/* ── Main ───────────────────────────────────────────────── */}
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
