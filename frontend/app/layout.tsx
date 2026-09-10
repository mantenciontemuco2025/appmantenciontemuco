import type { Metadata, Viewport } from "next";
import "./globals.css";
import { PwaClientFeatures } from "@/components/pwa-client-features";

export const metadata: Metadata = {
  title: "Plataforma de Mantención",
  description: "Registro de mantención para equipos industriales",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#2563eb",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es">
      <body className="min-h-screen bg-background text-foreground antialiased">
        {children}
        <PwaClientFeatures />
      </body>
    </html>
  );
}
