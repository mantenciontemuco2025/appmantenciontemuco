import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Términos del servicio | AppMantencion",
  description: "Términos de uso de la Plataforma de Mantención.",
};

const contactEmail = "mantenciontemuco2025@gmail.com";

export default function TermsPage() {
  return (
    <main className="min-h-screen bg-slate-50 px-4 py-10 text-slate-900 sm:px-6">
      <article className="mx-auto max-w-4xl rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-10">
        <header className="mb-8 border-b border-slate-200 pb-6">
          <p className="mb-3 text-sm font-semibold uppercase tracking-wide text-blue-700">AppMantencion</p>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Términos del servicio</h1>
          <p className="mt-3 text-sm text-slate-600">Última actualización: 28 de septiembre de 2026</p>
        </header>

        <div className="space-y-8 text-[15px] leading-7 text-slate-700">
          <section>
            <h2 className="mb-2 text-xl font-semibold text-slate-900">1. Objeto del servicio</h2>
            <p>
              AppMantencion es una plataforma interna para registrar, asignar, ejecutar, revisar y cerrar órdenes de
              trabajo y actividades de mantención. También permite administrar equipos, materiales, hallazgos,
              evidencias e informes operativos.
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-xl font-semibold text-slate-900">2. Acceso y cuentas</h2>
            <p>
              El acceso se entrega según el rol y los permisos definidos por la organización. Cada usuario debe mantener
              sus credenciales en reserva, utilizar únicamente su propia cuenta y avisar si detecta un acceso no
              autorizado.
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-xl font-semibold text-slate-900">3. Uso permitido</h2>
            <p>
              La plataforma debe utilizarse para fines operativos de mantención. Los usuarios deben ingresar información
              exacta, respetar los permisos asignados y adjuntar únicamente archivos relacionados con las actividades
              registradas.
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-xl font-semibold text-slate-900">4. Responsabilidad sobre los registros</h2>
            <p>
              La persona que crea, completa o revisa una orden de trabajo es responsable de la información que registra.
              Las aprobaciones, devoluciones, asignaciones y modificaciones pueden quedar registradas para fines de
              trazabilidad y auditoría.
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-xl font-semibold text-slate-900">5. Integraciones y documentos</h2>
            <p>
              Cuando se habilita Google Drive o Google Sheets, la plataforma puede crear o actualizar documentos de las
              órdenes de trabajo y cargar evidencias. El uso de esas integraciones depende de los permisos otorgados y
              de la disponibilidad de los servicios externos.
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-xl font-semibold text-slate-900">6. Disponibilidad y cambios</h2>
            <p>
              El servicio puede requerir mantenimiento, actualizaciones o interrupciones de proveedores externos. La
              organización puede modificar funciones, permisos o estos términos cuando sea necesario para mantener la
              seguridad y operación de la plataforma.
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-xl font-semibold text-slate-900">7. Contacto</h2>
            <p>
              Para consultas sobre estos términos o el funcionamiento de la plataforma, escribe a{" "}
              <a className="font-medium text-blue-700 underline" href={`mailto:${contactEmail}`}>
                {contactEmail}
              </a>
              .
            </p>
          </section>
        </div>

        <footer className="mt-10 border-t border-slate-200 pt-6 text-sm text-slate-600">
          <a className="font-medium text-blue-700 hover:underline" href="/login">Volver a AppMantencion</a>
        </footer>
      </article>
    </main>
  );
}
