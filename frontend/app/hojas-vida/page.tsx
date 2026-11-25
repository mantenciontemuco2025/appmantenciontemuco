"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AlignmentType, BorderStyle, Document, Footer, Header, ImageRun, PageBreak, Packer, Paragraph, Table, TableCell, TableRow, VerticalAlign, WidthType } from "docx";
import { Download, ExternalLink, FileSpreadsheet, FileText, Loader2, QrCode, RefreshCw, Search, X } from "lucide-react";
import { QRCodeCanvas, QRCodeSVG } from "qrcode.react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { Shell } from "@/components/layout/shell";
import { PageLoading } from "@/components/ui/page-loading";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { EquipmentLifeBackfillAccepted, EquipmentLifeBackfillStatus, EquipmentLifeDetail, EquipmentLifeSummary } from "@/lib/types";

const UNASSIGNED_AREA_KEY = "__sin_area_general__";

async function createQrLabelImage(url: string, equipmentName: string): Promise<Uint8Array> {
  const qrHost = document.createElement("div");
  qrHost.style.position = "fixed";
  qrHost.style.left = "-10000px";
  qrHost.style.top = "0";
  document.body.appendChild(qrHost);
  const qrRoot = createRoot(qrHost);
  try {
    flushSync(() => qrRoot.render(<QRCodeCanvas value={url} size={620} level="M" includeMargin />));
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    const qrCanvas = qrHost.querySelector("canvas");
    if (!qrCanvas) throw new Error("El navegador no pudo dibujar el código QR.");

    const logo = new Image();
    logo.src = "/logo.png";
    try {
      await logo.decode();
    } catch {
      throw new Error("No se pudo cargar el logo para la etiqueta.");
    }

    const canvas = document.createElement("canvas");
    canvas.width = 760;
    canvas.height = 960;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("No se pudo preparar una etiqueta QR.");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);

    const logoWidth = 540;
    const logoHeight = logoWidth * (logo.height / logo.width);
    context.drawImage(logo, (canvas.width - logoWidth) / 2, 30, logoWidth, logoHeight);
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillStyle = "#52504b";
    context.font = "bold 28px Arial, sans-serif";
    context.fillText("HOJA DE VIDA DEL EQUIPO", canvas.width / 2, 250);

    context.fillStyle = "#172033";
    context.font = "bold 36px Arial, sans-serif";
    const lines: string[] = [];
    let line = "";
    for (const word of equipmentName.trim().split(/\s+/)) {
      const candidate = line ? `${line} ${word}` : word;
      if (line && context.measureText(candidate).width > 680) {
        lines.push(line);
        line = word;
      } else {
        line = candidate;
      }
    }
    if (line) lines.push(line);
    const nameStart = 300;
    lines.slice(0, 3).forEach((nameLine, index) => context.fillText(nameLine, canvas.width / 2, nameStart + index * 44, 680));

    const qrSize = 420;
    const qrTop = Math.max(440, nameStart + Math.min(lines.length, 3) * 44 + 20);
    context.drawImage(qrCanvas, (canvas.width - qrSize) / 2, qrTop, qrSize, qrSize);
    context.fillStyle = "#f2b51b";
    context.fillRect(100, 930, canvas.width - 200, 5);

    const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob((value) => value ? resolve(value) : reject(new Error("No se pudo crear la imagen QR.")), "image/png"));
    return new Uint8Array(await blob.arrayBuffer());
  } finally {
    qrRoot.unmount();
    qrHost.remove();
  }
}

function safeFileName(value: string) {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9-_]+/gi, "-").replace(/^-|-$/g, "") || "area";
}

function statusLabel(status: string) {
  if (status === "SYNCED") return "Sincronizada";
  if (status === "FAILED") return "Con error";
  return "Pendiente";
}

function dateLabel(value: string | null) {
  if (!value) return "—";
  const [year, month, day] = value.slice(0, 10).split("-");
  return day && month && year ? `${day}-${month}-${year}` : value;
}

export default function EquipmentLifePage() {
  const { user, loading, logout } = useAuth();
  const [items, setItems] = useState<EquipmentLifeSummary[]>([]);
  const [selected, setSelected] = useState<EquipmentLifeDetail | null>(null);
  const [search, setSearch] = useState("");
  const [sectionFilter, setSectionFilter] = useState("");
  const [onlyWithRecords, setOnlyWithRecords] = useState(false);
  const [loadingData, setLoadingData] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillMode, setBackfillMode] = useState<"all" | "failed" | null>(null);
  const [backfillStatus, setBackfillStatus] = useState<EquipmentLifeBackfillStatus | null>(null);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [qrEquipment, setQrEquipment] = useState<{ name: string; url: string } | null>(null);
  const qrCanvasContainer = useRef<HTMLDivElement>(null);
  const [sharingQrEquipmentId, setSharingQrEquipmentId] = useState<number | null>(null);
  const [qrDocumentArea, setQrDocumentArea] = useState("");
  const [qrDocumentProgress, setQrDocumentProgress] = useState<{ done: number; total: number; equipment: string } | null>(null);

  async function loadItems() {
    setLoadingData(true);
    setMessage(null);
    try {
      setItems(await api.get<EquipmentLifeSummary[]>("/api/equipment-life"));
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "No se pudo cargar el historial." });
    } finally {
      setLoadingData(false);
    }
  }

  useEffect(() => {
    if (user) void loadItems();
  }, [user]);

  async function openDetail(item: EquipmentLifeSummary) {
    setLoadingDetail(true);
    setMessage(null);
    try {
      setSelected(await api.get<EquipmentLifeDetail>(`/api/equipment-life/${item.equipment_id}`));
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "No se pudo cargar la hoja de vida." });
    } finally {
      setLoadingDetail(false);
    }
  }

  async function getBackfillStatusWithRetry() {
    let lastError: unknown;
    for (let retry = 0; retry < 3; retry += 1) {
      try {
        return await api.get<EquipmentLifeBackfillStatus>("/api/equipment-life/status");
      } catch (error) {
        lastError = error;
        if (retry < 2) await new Promise((resolve) => window.setTimeout(resolve, 2000));
      }
    }
    throw lastError instanceof Error ? lastError : new Error("No se pudo consultar el avance de la importación.");
  }

  async function backfill(retryFailedOnly = false) {
    const failedCount = items.filter((item) => item.life_sheet_sync_status === "FAILED").length;
    const confirmation = retryFailedOnly
      ? `Se reintentará la sincronización de ${failedCount} hoja(s) con error. Las hojas ya sincronizadas no se modificarán. ¿Continuar?`
      : "Se reconstruirán todas las hojas de vida desde las OT guardadas en la app. Se reemplazará la tabla del historial en Drive, incluidas ediciones manuales hechas directamente en esas hojas. ¿Continuar?";
    if (!window.confirm(confirmation)) return;
    setBackfilling(true);
    setBackfillMode(retryFailedOnly ? "failed" : "all");
    setBackfillStatus(null);
    setMessage(null);
    try {
      const accepted = await api.post<EquipmentLifeBackfillAccepted>("/api/equipment-life/backfill", { include_drafts: false, retry_failed_only: retryFailedOnly }, 30000);
      setMessage({ kind: "success", text: accepted.message });
      let statusFailures = 0;
      for (let attempt = 0; attempt < 180; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 5000));
        let state: EquipmentLifeBackfillStatus;
        try {
          state = await getBackfillStatusWithRetry();
          statusFailures = 0;
        } catch (error) {
          statusFailures += 1;
          if (statusFailures >= 3) throw error;
          setMessage({ kind: "success", text: "No se pudo consultar temporalmente el avance. La importación puede seguir ejecutándose; reintentando..." });
          continue;
        }
        setBackfillStatus(state);
        await loadItems();
        if (state.status === "running") {
          const sheetsTotal = state.sheets_total;
          const sheetsProcessed = state.sheets_processed;
          const percent = sheetsTotal > 0 ? Math.min(100, Math.round((sheetsProcessed / sheetsTotal) * 100)) : 0;
          const current = state.current_equipment ? ` Se está actualizando: ${state.current_equipment}.` : "";
          setMessage({ kind: "success", text: `Sincronización ${percent}%: ${sheetsProcessed} de ${sheetsTotal} hojas completas; ${state.work_orders_synced} de ${state.work_orders_total} OT sincronizadas.${current}` });
        }
        if (state.status === "completed") {
          const completed = state.result;
          setMessage({ kind: state.errors_count ? "error" : "success", text: completed ? `Actualización terminada: ${completed.sheets_synced} de ${state.sheets_total} hojas procesadas, ${completed.work_orders_synced} OT sincronizadas${state.errors_count ? ` y ${state.errors_count} hojas con error. Detalles: ${completed.errors.slice(0, 3).join(" | ")}` : ""}. ${completed.work_orders_without_equipment} OT quedaron sin equipo.` : "Actualización terminada correctamente." });
          if (selected) await openDetail(selected);
          return;
        }
        if (state.status === "failed") {
          throw new Error(state.error || "La importaciÃ³n fallÃ³. Revisa el estado del backend.");
        }
        if (attempt === 179) throw new Error("La importaciÃ³n sigue en curso. Revisa nuevamente en unos minutos.");
      }
      return;
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "No se pudo ejecutar la importación." });
    } finally {
      setBackfilling(false);
      setBackfillMode(null);
    }
  }

  async function downloadEquipmentQr() {
    const canvas = qrCanvasContainer.current?.querySelector("canvas");
    if (!canvas || !qrEquipment) return;
    const logo = new Image();
    logo.src = "/logo.png";
    try {
      await logo.decode();
    } catch {
      setMessage({ kind: "error", text: "No se pudo cargar el logo de Maltexco para crear el QR." });
      return;
    }

    const output = document.createElement("canvas");
    const context = output.getContext("2d");
    if (!context) return;

    const width = 900;
    const qrSize = 500;
    const nameFontSize = 38;
    context.font = `bold ${nameFontSize}px Arial, sans-serif`;
    const lines: string[] = [];
    let line = "";
    for (const word of qrEquipment.name.trim().split(/\s+/)) {
      const candidate = line ? `${line} ${word}` : word;
      if (line && context.measureText(candidate).width > 760) {
        lines.push(line);
        line = word;
      } else {
        line = candidate;
      }
    }
    if (line) lines.push(line);

    const qrTop = 430 + lines.length * 50 + 20;
    const footerTop = qrTop + qrSize + 50;
    output.width = width;
    output.height = footerTop + 85;
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, output.width, output.height);

    const logoWidth = 620;
    const logoHeight = logoWidth * (logo.height / logo.width);
    context.drawImage(logo, (width - logoWidth) / 2, 42, logoWidth, logoHeight);

    context.fillStyle = "#52504b";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.font = "bold 28px Arial, sans-serif";
    context.fillText("HOJA DE VIDA DEL EQUIPO", width / 2, 380);
    context.fillStyle = "#172033";
    context.font = `bold ${nameFontSize}px Arial, sans-serif`;
    lines.forEach((nameLine, index) => {
      context.fillText(nameLine, width / 2, 430 + index * 50, 760);
    });

    context.drawImage(canvas, (width - qrSize) / 2, qrTop, qrSize, qrSize);
    context.fillStyle = "#f2b51b";
    context.fillRect(110, footerTop, width - 220, 5);
    context.fillStyle = "#52504b";
    context.font = "24px Arial, sans-serif";
    context.fillText("Escanea para consultar el historial del equipo", width / 2, footerTop + 43);

    const link = document.createElement("a");
    const safeName = qrEquipment.name.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9-_]+/gi, "-").replace(/^-|-$/g, "");
    link.download = `QR-MALTEXCO-${safeName || "equipo"}.png`;
    link.href = output.toDataURL("image/png");
    link.click();
  }

  async function openPublicQr(equipmentId: number, equipmentName: string) {
    setSharingQrEquipmentId(equipmentId);
    setMessage(null);
    try {
      const result = await api.post<{ token: string; drive_url: string }>(`/api/equipment-life/${equipmentId}/public-link`, {});
      const publicUrl = new URL(`/public/hojas-vida/${encodeURIComponent(result.token)}`, window.location.origin).toString();
      setQrEquipment({ name: equipmentName, url: publicUrl });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "No se pudo habilitar el acceso de lectura en Drive." });
    } finally {
      setSharingQrEquipmentId(null);
    }
  }

  async function downloadAreaQrDocument() {
    const areaItems = items.filter((item) => {
      const matchesArea = qrDocumentArea === UNASSIGNED_AREA_KEY
        ? !item.plant_area_name?.trim()
        : item.plant_area_name === qrDocumentArea;
      return matchesArea && item.life_sheet_file_id && item.life_sheet_url;
    });
    if (!areaItems.length || !user || user.role !== "ADMIN") return;
    const areaLabel = qrDocumentArea === UNASSIGNED_AREA_KEY ? "Sin área" : qrDocumentArea;
    if (!window.confirm(`Se preparará un Word para “${areaLabel}” con ${areaItems.length} equipos. Para que sus QR funcionen, se habilitará el acceso público de solo lectura a cada hoja de vida en Drive. ¿Continuar?`)) return;

    setQrDocumentProgress({ done: 0, total: areaItems.length, equipment: areaItems[0].equipment_name });
    setMessage(null);
    const labels: { name: string; image: Uint8Array }[] = [];
    const failures: string[] = [];
    try {
      for (let index = 0; index < areaItems.length; index += 1) {
        const item = areaItems[index];
        setQrDocumentProgress({ done: index, total: areaItems.length, equipment: item.equipment_name });
        try {
          const result = await api.post<{ token: string; drive_url: string }>(`/api/equipment-life/${item.equipment_id}/public-link`, {});
          const url = new URL(`/public/hojas-vida/${encodeURIComponent(result.token)}`, window.location.origin).toString();
          labels.push({ name: item.equipment_name, image: await createQrLabelImage(url, item.equipment_name) });
        } catch (error) {
          failures.push(`${item.equipment_name}: ${error instanceof Error ? error.message : "no se pudo crear el QR"}`);
        }
        setQrDocumentProgress({ done: index + 1, total: areaItems.length, equipment: item.equipment_name });
      }
      if (!labels.length) {
        const detail = failures.slice(0, 3).join(" | ");
        throw new Error(`No se pudo generar ningún QR para esta área.${detail ? ` Detalle: ${detail}` : ""}`);
      }

      const tableBorder = { style: BorderStyle.SINGLE, size: 6, color: "D4D9E2" };
      const tableCellFor = (label?: { name: string; image: Uint8Array }) => new TableCell({
        width: { size: 4680, type: WidthType.DXA },
        verticalAlign: VerticalAlign.CENTER,
        margins: { top: 45, bottom: 45, left: 60, right: 60 },
        borders: { top: tableBorder, bottom: tableBorder, left: tableBorder, right: tableBorder },
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: label ? [new ImageRun({ type: "png", data: label.image, transformation: { width: 338, height: 427 } })] : [],
        })],
      });
      const pageChildren = [];
      for (let offset = 0; offset < labels.length; offset += 4) {
        if (offset > 0) pageChildren.push(new Paragraph({ children: [new PageBreak()] }));
        const pageLabels = labels.slice(offset, offset + 4);
        pageChildren.push(new Table({
          width: { size: 10800, type: WidthType.DXA },
          columnWidths: [5400, 5400],
          rows: [
            new TableRow({ cantSplit: true, children: [tableCellFor(pageLabels[0]), tableCellFor(pageLabels[1])] }),
            new TableRow({ cantSplit: true, children: [tableCellFor(pageLabels[2]), tableCellFor(pageLabels[3])] }),
          ],
        }));
      }
      const document = new Document({
        sections: [{
          properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 720, bottom: 720, left: 720, right: 720 } } },
          headers: { default: new Header({ children: [new Paragraph({ text: `MALTEXCO · ${areaLabel.toLocaleUpperCase("es")}`, alignment: AlignmentType.CENTER })] }) },
          footers: { default: new Footer({ children: [new Paragraph({ text: "Escanea el código para abrir la hoja de vida del equipo", alignment: AlignmentType.CENTER })] }) },
          children: pageChildren,
        }],
      });
      const blob = await Packer.toBlob(document);
      const downloadUrl = URL.createObjectURL(blob);
      const link = window.document.createElement("a");
      link.href = downloadUrl;
      link.download = `QR-${safeFileName(areaLabel)}.docx`;
      link.click();
      URL.revokeObjectURL(downloadUrl);
      setMessage(failures.length
        ? { kind: "error", text: `Se creó el Word con ${labels.length} QR. ${failures.length} equipos se omitieron: ${failures.slice(0, 3).join(" | ")}` }
        : { kind: "success", text: `Documento Word creado para ${areaLabel}: ${labels.length} QR, cuatro por página.` });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "No se pudo crear el documento Word." });
    } finally {
      setQrDocumentProgress(null);
    }
  }

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((item) => [item.equipment_name, item.section_name, item.plant_area_name].some((value) => value?.toLowerCase().includes(needle)));
  }, [items, search]);

  const sections = useMemo(() => Array.from(new Set(items.filter((item) => item.work_order_count > 0 && item.section_name).map((item) => item.section_name as string))).sort((a, b) => a.localeCompare(b, "es")), [items]);
  const qrDocumentAreas = useMemo(() => {
    const assigned = Array.from(new Set(items.filter((item) => item.life_sheet_file_id && item.life_sheet_url && item.plant_area_name?.trim()).map((item) => item.plant_area_name as string))).sort((a, b) => a.localeCompare(b, "es"));
    const hasUnassigned = items.some((item) => item.life_sheet_file_id && item.life_sheet_url && !item.plant_area_name?.trim());
    return hasUnassigned ? [UNASSIGNED_AREA_KEY, ...assigned] : assigned;
  }, [items]);
  const qrDocumentEquipmentCount = items.filter((item) => {
    const matchesArea = qrDocumentArea === UNASSIGNED_AREA_KEY
      ? !item.plant_area_name?.trim()
      : item.plant_area_name === qrDocumentArea;
    return matchesArea && item.life_sheet_file_id && item.life_sheet_url;
  }).length;
  const qrDocumentAreaLabel = qrDocumentArea === UNASSIGNED_AREA_KEY ? "Sin área" : qrDocumentArea;
  const visibleItems = useMemo(() => filtered.filter((item) => (!onlyWithRecords || item.work_order_count > 0) && (!sectionFilter || item.section_name === sectionFilter)), [filtered, onlyWithRecords, sectionFilter]);

  if (loading || !user) return <PageLoading message={loading ? "Validando sesión..." : "Redirigiendo..."} />;

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div><h1 className="text-2xl font-bold">Hojas de vida de equipos</h1><p className="mt-1 text-sm text-muted-foreground">Historial de trabajos por equipo, guardado en la base de datos y en Google Drive.</p></div>
        <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => void loadItems()} disabled={loadingData}><RefreshCw className="mr-2 h-4 w-4" />Actualizar</Button>{user.role === "ADMIN" && items.some((item) => item.life_sheet_sync_status === "FAILED") && <Button variant="outline" onClick={() => void backfill(true)} disabled={backfilling}><RefreshCw className={`mr-2 h-4 w-4 ${backfilling && backfillMode === "failed" ? "animate-spin" : ""}`} />{backfilling && backfillMode === "failed" ? "Reintentando con error..." : `Reintentar con error (${items.filter((item) => item.life_sheet_sync_status === "FAILED").length})`}</Button>}{user.role === "ADMIN" && <Button onClick={() => void backfill(false)} disabled={backfilling}>{backfilling && backfillMode === "all" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileSpreadsheet className="mr-2 h-4 w-4" />}{backfilling && backfillMode === "all" ? "Actualizando hojas..." : "Actualizar todas las hojas"}</Button>}</div>
      </div>

      {message && <div className={`mb-4 rounded-lg border p-3 text-sm ${message.kind === "error" ? "border-red-200 bg-red-50 text-red-800" : "border-green-200 bg-green-50 text-green-800"}`}>{message.text}</div>}

      {user.role === "ADMIN" && <section className="mb-4 rounded-xl border bg-card p-4 shadow-sm"><div className="flex flex-wrap items-end gap-3"><div className="min-w-64 flex-1"><h2 className="font-semibold">Imprimir códigos QR por área</h2><p className="mt-1 text-sm text-muted-foreground">Crea un Word por área, con cuatro etiquetas por página. Se incluyen equipos con hoja de vida en Drive.</p><label className="mt-3 block text-sm font-medium">Área general<select className="mt-1 h-10 w-full rounded-md border bg-background px-3 font-normal" value={qrDocumentArea} onChange={(event) => setQrDocumentArea(event.target.value)} disabled={!!qrDocumentProgress}><option value="">Selecciona un área</option>{qrDocumentAreas.map((area) => <option key={area} value={area}>{area === UNASSIGNED_AREA_KEY ? "Sin área" : area}</option>)}</select></label></div><Button onClick={() => void downloadAreaQrDocument()} disabled={!qrDocumentArea || !qrDocumentEquipmentCount || !!qrDocumentProgress}><FileText className="mr-2 h-4 w-4" />{qrDocumentProgress ? `Preparando ${qrDocumentProgress.done}/${qrDocumentProgress.total}...` : `Descargar Word de ${qrDocumentAreaLabel || "área"}`}</Button></div>{qrDocumentArea && <p className="mt-2 text-xs text-muted-foreground">{qrDocumentEquipmentCount} equipos incluidos. El proceso habilita lectura pública de sus hojas de vida en Drive para que los QR puedan abrirlas.</p>}{qrDocumentProgress && <div className="mt-3"><div className="mb-1 flex justify-between text-xs text-muted-foreground"><span>Preparando: {qrDocumentProgress.equipment}</span><span>{Math.round((qrDocumentProgress.done / qrDocumentProgress.total) * 100)}%</span></div><div className="h-2 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary transition-all" style={{ width: `${Math.round((qrDocumentProgress.done / qrDocumentProgress.total) * 100)}%` }} /></div></div>}</section>}

      {backfilling && backfillStatus?.status === "running" && (() => {
        const percent = backfillStatus.sheets_total > 0 ? Math.min(100, Math.round((backfillStatus.sheets_processed / backfillStatus.sheets_total) * 100)) : 0;
        return <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950">
          <div className="mb-2 flex items-center justify-between font-semibold"><span>{backfillMode === "failed" ? "Reintentando solo las hojas con error" : "Actualizando hojas una por una"}</span><span>{percent}%</span></div>
          <div className="h-2 overflow-hidden rounded-full bg-blue-100"><div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${percent}%` }} /></div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs"><span>Hojas completas: {backfillStatus.sheets_processed}/{backfillStatus.sheets_total}</span><span>OT sincronizadas: {backfillStatus.work_orders_synced}/{backfillStatus.work_orders_total}</span>{backfillStatus.errors_count > 0 && <span>Hojas con error: {backfillStatus.errors_count}</span>}{backfillStatus.current_equipment && <span>Actualizando: {backfillStatus.current_equipment}</span>}</div>
        </div>;
      })()}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <section className="rounded-xl border bg-card p-4">
          <div className="mb-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_180px]"><div className="relative"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><input className="h-10 w-full rounded-md border bg-background pl-9 pr-3 text-sm" placeholder="Buscar equipo o sección..." value={search} onChange={(event) => setSearch(event.target.value)} /></div><select className="h-10 rounded-md border bg-background px-3 text-sm" value={sectionFilter} onChange={(event) => setSectionFilter(event.target.value)}><option value="">Secciones con registros</option>{sections.map((section) => <option key={section} value={section}>{section}</option>)}</select></div>
          <label className="mb-3 flex items-center gap-2 text-sm text-muted-foreground"><input type="checkbox" checked={onlyWithRecords} onChange={(event) => setOnlyWithRecords(event.target.checked)} className="h-4 w-4 rounded border-input" />Solo equipos con registros ({items.filter((item) => item.work_order_count > 0).length})</label>
          {user.role === "ADMIN" && items.some((item) => item.life_sheet_sync_status === "FAILED") && <details className="mb-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900"><summary className="cursor-pointer font-medium">Ver errores de sincronización ({items.filter((item) => item.life_sheet_sync_status === "FAILED").length})</summary><ul className="mt-2 max-h-48 space-y-1 overflow-auto text-xs">{items.filter((item) => item.life_sheet_sync_status === "FAILED").map((item) => <li key={item.equipment_id}><strong>{item.equipment_name}:</strong> {item.life_sheet_sync_error || "El backend no entregó el detalle del error."}</li>)}</ul></details>}
          {loadingData ? <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Cargando equipos...</div> : <div className="max-h-[650px] space-y-2 overflow-auto">{visibleItems.map((item) => <div key={item.equipment_id} className={`flex items-center gap-2 rounded-lg border p-3 transition-colors hover:border-primary ${selected?.equipment_id === item.equipment_id ? "border-primary bg-primary/5" : ""}`}><button type="button" onClick={() => void openDetail(item)} className="min-w-0 flex-1 text-left"><div className="truncate font-semibold">{item.equipment_name}</div><div className="mt-1 text-xs text-muted-foreground">{item.section_name || "Sin sección"}{item.plant_area_name ? ` · ${item.plant_area_name}` : ""}</div><div className="mt-2 flex items-center justify-between text-xs"><span>{item.work_order_count} OT registradas</span><span className={item.life_sheet_sync_status === "SYNCED" ? "text-green-700" : item.life_sheet_sync_status === "FAILED" ? "text-red-700" : "text-amber-700"}>{statusLabel(item.life_sheet_sync_status)}</span></div></button>{user.role === "ADMIN" && item.life_sheet_url && <button type="button" onClick={() => void openPublicQr(item.equipment_id, item.equipment_name)} disabled={sharingQrEquipmentId === item.equipment_id} className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border text-muted-foreground hover:border-primary hover:text-primary disabled:opacity-50" aria-label={`Habilitar y descargar QR de ${item.equipment_name}`} title="Habilitar acceso público y descargar QR">{sharingQrEquipmentId === item.equipment_id ? <Loader2 className="h-4 w-4 animate-spin" /> : <QrCode className="h-4 w-4" />}</button>}</div>)}{!visibleItems.length && <p className="py-8 text-sm text-muted-foreground">No hay equipos que coincidan con los filtros.</p>}</div>}
        </section>

        <section className="rounded-xl border bg-card p-4">
          {!selected ? <div className="flex min-h-[240px] items-center justify-center text-center text-sm text-muted-foreground">Selecciona un equipo para ver sus registros.</div> : <><div className="flex flex-wrap items-start justify-between gap-3 border-b pb-3"><div><h2 className="text-xl font-semibold">{selected.equipment_name}</h2><p className="text-sm text-muted-foreground">{selected.section_name || "Sin sección"}{selected.plant_area_name ? ` · ${selected.plant_area_name}` : ""}</p></div><div className="flex gap-3">{user.role === "ADMIN" && selected.life_sheet_url && <button type="button" onClick={() => void openPublicQr(selected.equipment_id, selected.equipment_name)} disabled={sharingQrEquipmentId === selected.equipment_id} className="inline-flex items-center gap-1 text-sm text-primary hover:underline disabled:opacity-50">{sharingQrEquipmentId === selected.equipment_id ? <Loader2 className="h-4 w-4 animate-spin" /> : <QrCode className="h-4 w-4" />}QR público</button>}{user.role !== "WORKER" && selected.life_sheet_url && <a className="inline-flex items-center gap-1 text-sm text-primary hover:underline" href={selected.life_sheet_url} target="_blank" rel="noreferrer">Abrir en Drive <ExternalLink className="h-3.5 w-3.5" /></a>}</div></div><div className="mt-4 overflow-x-auto"><table className="w-full min-w-[1320px] text-left text-sm"><thead><tr className="border-b text-xs uppercase text-muted-foreground"><th className="px-2 py-2">Fecha</th><th className="px-2 py-2">OT</th><th className="px-2 py-2">Trabajo</th><th className="px-2 py-2">Realizado por</th><th className="px-2 py-2">Autorizado por</th><th className="px-2 py-2">Observaciones</th><th className="px-2 py-2">Repuestos</th><th className="px-2 py-2">Tiempo real</th><th className="px-2 py-2">Estado</th><th className="px-2 py-2">Tipo</th></tr></thead><tbody>{selected.records.map((record) => <tr key={record.work_order_id} className="border-b last:border-0 align-top"><td className="px-2 py-2 whitespace-nowrap">{dateLabel(record.event_date)}</td><td className="px-2 py-2 whitespace-nowrap font-medium"><Link className="text-primary hover:underline" href={`/hojas-vida/ordenes/${selected.equipment_id}/${record.work_order_id}`}>{record.ot_number}</Link></td><td className="max-w-[240px] px-2 py-2">{record.description || record.title}</td><td className="px-2 py-2">{record.performed_by || "—"}</td><td className="px-2 py-2">{record.authorized_by || "—"}</td><td className="max-w-[240px] px-2 py-2">{record.observations || "—"}</td><td className="max-w-[220px] px-2 py-2">{record.resources_required || "—"}</td><td className="px-2 py-2 whitespace-nowrap">{record.worked_duration || "—"}</td><td className="px-2 py-2">{record.status}</td><td className="px-2 py-2">{record.maintenance_type}</td></tr>)}</tbody></table>{!selected.records.length && <p className="py-8 text-sm text-muted-foreground">Este equipo aún no tiene OT registradas.</p>}</div></>}
          {loadingDetail && <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Cargando detalle...</div>}
        </section>
      </div>
      {qrEquipment && <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-labelledby="equipment-qr-title" onMouseDown={(event) => { if (event.target === event.currentTarget) setQrEquipment(null); }}><div className="w-full max-w-sm rounded-xl border bg-card p-5 shadow-xl"><div className="mb-4 flex items-start justify-between gap-3"><div><h2 id="equipment-qr-title" className="text-lg font-semibold">Hoja de vida: {qrEquipment.name}</h2><p className="text-sm text-muted-foreground">El QR abre la ficha pública de solo lectura en la app. El PNG llevará el logo Maltexco y el nombre del equipo.</p></div><button type="button" onClick={() => setQrEquipment(null)} className="rounded-md p-1 text-muted-foreground hover:bg-muted" aria-label="Cerrar código QR"><X className="h-5 w-5" /></button></div><div ref={qrCanvasContainer} className="flex justify-center rounded-lg bg-white p-4"><QRCodeCanvas value={qrEquipment.url} size={240} level="M" includeMargin /></div><p className="mt-3 text-xs text-muted-foreground">La ficha permite consultar el historial y abrir los documentos disponibles en Drive. No muestra controles de edición ni otro QR.</p><div className="mt-4 flex gap-2"><Button className="flex-1" onClick={() => void downloadEquipmentQr()}><Download className="mr-2 h-4 w-4" />Descargar QR PNG</Button><a href={qrEquipment.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-md border px-3 text-sm hover:bg-muted"><ExternalLink className="h-4 w-4" />Abrir</a></div></div></div>}
    </Shell>
  );
}
