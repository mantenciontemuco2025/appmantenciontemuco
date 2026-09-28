import type { Metadata } from "next";
import Link from "next/link";
import { ClipboardCheck, FileText, ShieldCheck, Wrench } from "lucide-react";

export const metadata: Metadata = {
  title: "AppMantencion | Gestión de mantenimiento",
  description:
    "AppMantencion permite gestionar órdenes de trabajo, mantención, equipos, hallazgos e informes operativos.",
};

export default function HomePage() {
  return (
    <main className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4 sm:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 text-white">
              <Wrench className="h-5 w-5" aria-hidden="true" />
            </div>
            <span className="text-lg font-bold tracking-tight">AppMantencion</span>
          </div>
          <Link href="/login" className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-700">
            Iniciar sesión
          </Link>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-24">
        <div className="max-w-3xl">
          <p className="mb-4 text-sm font-semibold uppercase tracking-[0.18em] text-blue-700">
            Plataforma de gestión de mantenimiento
          </p>
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">AppMantencion</h1>
          <p className="mt-5 max-w-2xl text-lg leading-8 text-slate-600">
            Plataforma para planificar, asignar, ejecutar, revisar y cerrar órdenes de trabajo,
            además de administrar equipos, hallazgos, evidencias, materiales e informes operativos.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/login" className="rounded-lg bg-blue-600 px-5 py-3 font-semibold text-white transition hover:bg-blue-700">
              Acceder a la plataforma
            </Link>
            <Link href="/privacidad" className="rounded-lg border border-slate-300 bg-white px-5 py-3 font-semibold text-slate-700 transition hover:bg-slate-100">
              Ver política de privacidad
            </Link>
          </div>
        </div>

        <div className="mt-16 grid gap-5 md:grid-cols-3">
          <article className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <ClipboardCheck className="h-7 w-7 text-blue-600" aria-hidden="true" />
            <h2 className="mt-4 text-lg font-semibold">Órdenes de trabajo</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">Seguimiento de solicitudes, responsables, tiempos, estados, aprobaciones y devoluciones.</p>
          </article>
          <article className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <ShieldCheck className="h-7 w-7 text-blue-600" aria-hidden="true" />
            <h2 className="mt-4 text-lg font-semibold">Trazabilidad y seguridad</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">Acceso según roles, historial de cambios, validaciones y registros de auditoría.</p>
          </article>
          <article className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <FileText className="h-7 w-7 text-blue-600" aria-hidden="true" />
            <h2 className="mt-4 text-lg font-semibold">Informes operativos</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">Indicadores y registros para apoyar la gestión diaria de mantenimiento.</p>
          </article>
        </div>
      </section>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-6 text-sm text-slate-600 sm:px-8">
          <span>AppMantencion</span>
          <nav className="flex gap-4" aria-label="Enlaces legales">
            <Link className="hover:text-blue-700 hover:underline" href="/privacidad">Política de privacidad</Link>
            <Link className="hover:text-blue-700 hover:underline" href="/terminos">Términos del servicio</Link>
          </nav>
        </div>
      </footer>
    </main>
  );
}
