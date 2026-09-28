import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Política de privacidad | AppMantencion",
  description: "Política de privacidad de la Plataforma de Mantención.",
};

const contactEmail = "mantenciontemuco2025@gmail.com";

export default function PrivacyPage() {
  return (
    <main className="min-h-screen bg-slate-50 px-4 py-10 text-slate-900 sm:px-6">
      <article className="mx-auto max-w-4xl rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-10">
        <header className="mb-8 border-b border-slate-200 pb-6">
          <p className="mb-3 text-sm font-semibold uppercase tracking-wide text-blue-700">AppMantencion</p>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Política de privacidad</h1>
          <p className="mt-3 text-sm text-slate-600">Última actualización: 28 de septiembre de 2026</p>
        </header>

        <div className="space-y-8 text-[15px] leading-7 text-slate-700">
          <section>
            <h2 className="mb-2 text-xl font-semibold text-slate-900">1. Alcance</h2>
            <p>
              Esta política explica cómo AppMantencion recopila, utiliza y protege la información de las personas que
              utilizan la Plataforma de Mantención para gestionar órdenes de trabajo, hallazgos, personal, equipos y
              registros operativos.
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-xl font-semibold text-slate-900">2. Información que podemos tratar</h2>
            <ul className="list-disc space-y-1 pl-5">
              <li>Nombre, correo, rol y datos necesarios para crear la cuenta.</li>
              <li>Órdenes de trabajo, responsables, fechas, tiempos, observaciones y estados.</li>
              <li>Información de equipos, áreas, secciones, materiales y registros operativos.</li>
              <li>Fotografías y otros archivos adjuntados como evidencia de una orden de trabajo.</li>
              <li>Registros técnicos necesarios para seguridad, auditoría y funcionamiento del servicio.</li>
            </ul>
          </section>

          <section>
            <h2 className="mb-2 text-xl font-semibold text-slate-900">3. Uso de la información</h2>
            <p>La información se utiliza para:</p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>Autenticar usuarios y aplicar permisos según su rol.</li>
              <li>Crear, asignar, ejecutar, revisar y cerrar órdenes de trabajo.</li>
              <li>Generar informes, indicadores, notificaciones y registros de auditoría.</li>
              <li>Guardar documentos y evidencias en los servicios autorizados por la organización.</li>
              <li>Detectar errores, mantener la seguridad y mejorar la plataforma.</li>
            </ul>
          </section>

          <section>
            <h2 className="mb-2 text-xl font-semibold text-slate-900">4. Integración con Google</h2>
            <p>
              Si la organización habilita la integración con Google Drive o Google Sheets, AppMantencion utiliza los
              permisos autorizados para crear, actualizar o consultar documentos relacionados con las órdenes de
              trabajo y sus evidencias. La aplicación no vende esta información ni la utiliza para publicidad.
            </p>
            <p className="mt-3">
              El acceso puede revocarse en cualquier momento desde la configuración de seguridad de la cuenta de Google.
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-xl font-semibold text-slate-900">5. Conservación y seguridad</h2>
            <p>
              Conservamos la información durante el tiempo necesario para la operación, auditoría y obligaciones de la
              organización. Aplicamos controles de acceso por rol, autenticación, registros de auditoría y medidas
              técnicas razonables para proteger los datos contra acceso, alteración o divulgación no autorizada.
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-xl font-semibold text-slate-900">6. Compartición de información</h2>
            <p>
              La información se comparte únicamente con usuarios autorizados de la organización y con proveedores
              tecnológicos necesarios para operar la plataforma, como servicios de alojamiento y Google Drive o Sheets
              cuando la integración está habilitada. No se comercializan datos personales.
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-xl font-semibold text-slate-900">7. Derechos y contacto</h2>
            <p>
              Para solicitar acceso, corrección, eliminación o información sobre el tratamiento de datos, escribe a{" "}
              <a className="font-medium text-blue-700 underline" href={`mailto:${contactEmail}`}>
                {contactEmail}
              </a>
              . Las solicitudes pueden estar sujetas a verificación de identidad y a las obligaciones de conservación
              aplicables a los registros operativos.
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
