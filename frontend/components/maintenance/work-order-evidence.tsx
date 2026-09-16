"use client";

import { useEffect, useState } from "react";
import { ImagePlus, Loader2, Camera } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";

type EvidenceStage = "ISSUE" | "WORK";

interface EvidenceItem {
  id: number;
  filename: string;
  mime_type: string;
  stage: EvidenceStage;
  uploaded_by_user_id: number | null;
  uploaded_by_name: string;
  uploaded_at: string;
}

function EvidencePhoto({ woId, item }: { woId: number; item: EvidenceItem }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    api.getBlob(`/api/work-orders/${woId}/evidence/${item.id}/content`)
      .then((blob) => {
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [woId, item.id]);

  return (
    <figure className="overflow-hidden rounded-lg border bg-background">
      <div className="flex aspect-video items-center justify-center bg-muted">
        {url ? (
          // The authenticated API returns a temporary object URL, not a public Drive link.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt={item.filename} className="h-full w-full object-cover" />
        ) : error ? (
          <span className="px-3 text-center text-xs text-muted-foreground">No se pudo cargar la foto</span>
        ) : (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        )}
      </div>
      <figcaption className="space-y-1 p-3 text-xs">
        <p className="truncate font-medium" title={item.filename}>{item.filename}</p>
        <p className="text-muted-foreground">
          {item.stage === "ISSUE" ? "Emisión" : "Trabajo realizado"} · {item.uploaded_by_name}
        </p>
        <p className="text-muted-foreground">
          {new Date(item.uploaded_at).toLocaleString("es-CL")}
        </p>
      </figcaption>
    </figure>
  );
}

export function WorkOrderEvidencePanel({
  woId,
  stage,
  canUpload,
  currentUserId,
}: {
  woId: number;
  stage: EvidenceStage;
  canUpload: boolean;
  currentUserId: number;
}) {
  const [items, setItems] = useState<EvidenceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function loadEvidence() {
    setLoading(true);
    try {
      setItems(await api.get<EvidenceItem[]>(`/api/work-orders/${woId}/evidence`));
      setMessage(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo cargar la evidencia.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadEvidence();
    // The panel is scoped to one OT.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [woId]);

  async function handleFiles(files: FileList | null, input: HTMLInputElement) {
    if (!files?.length) return;
    const ownCount = items.filter((item) => item.uploaded_by_user_id === currentUserId).length;
    const available = Math.max(0, 2 - ownCount);
    const selected = Array.from(files).slice(0, available);
    if (selected.length < files.length) {
      setMessage(`Cada usuario puede subir hasta 2 fotos por OT; te quedan ${available} espacio(s).`);
    } else {
      setMessage(null);
    }
    if (!selected.length) {
      input.value = "";
      return;
    }

    setUploading(true);
    try {
      for (const file of selected) {
        const form = new FormData();
        form.append("file", file);
        form.append("stage", stage);
        const item = await api.upload<EvidenceItem>(`/api/work-orders/${woId}/evidence`, form, 120000);
        setItems((current) => [...current, item]);
      }
      setMessage("Foto guardada en Google Drive.");
    } catch (error) {
      await loadEvidence();
      setMessage(error instanceof Error ? error.message : "No se pudo guardar la foto.");
    } finally {
      setUploading(false);
      input.value = "";
    }
  }

  const ownCount = items.filter((item) => item.uploaded_by_user_id === currentUserId).length;
  const available = Math.max(0, 2 - ownCount);
  return (
    <Card className="mb-4">
      <CardContent className="p-4">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 font-semibold">
              <Camera className="h-4 w-4 text-primary" /> Evidencia fotográfica
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              {stage === "ISSUE"
                ? "Adjunta fotos del equipo o la condición antes de emitir o enviar la OT."
                : "Adjunta fotos del trabajo realizado antes de finalizar la OT."}
              {" "}Cada usuario puede subir hasta 2 fotos por OT. Todos los autorizados a ver la OT pueden verlas; se guardan privadas en Drive y se comprimen automáticamente.
            </p>
          </div>
          {canUpload && available > 0 && (
            <div className="flex flex-wrap gap-2">
              <label className="inline-flex cursor-pointer">
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  capture="environment"
                  className="sr-only"
                  disabled={loading || uploading}
                  onChange={(event) => void handleFiles(event.currentTarget.files, event.currentTarget)}
                />
                <span className="inline-flex h-9 items-center rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90">
                  {uploading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Camera className="mr-2 h-4 w-4" />}
                  {uploading ? "Subiendo…" : "Tomar foto"}
                </span>
              </label>
              <label className="inline-flex cursor-pointer">
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  multiple
                  className="sr-only"
                  disabled={loading || uploading}
                  onChange={(event) => void handleFiles(event.currentTarget.files, event.currentTarget)}
                />
                <span className="inline-flex h-9 items-center rounded-md border border-input bg-background px-3 text-sm font-medium hover:bg-accent">
                  {uploading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <ImagePlus className="mr-2 h-4 w-4" />}
                  {uploading ? "Subiendo…" : `Elegir foto (${available} disponible${available === 1 ? "" : "s"})`}
                </span>
              </label>
            </div>
          )}
        </div>

        {message && (
          <p className="mb-3 text-sm text-muted-foreground" role="status">{message}</p>
        )}
        {loading ? (
          <div className="flex items-center gap-2 py-3 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Cargando fotos…
          </div>
        ) : items.length ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {items.map((item) => <EvidencePhoto key={item.id} woId={woId} item={item} />)}
          </div>
        ) : (
          <p className="py-2 text-sm text-muted-foreground">Todavía no hay fotos adjuntas.</p>
        )}
      </CardContent>
    </Card>
  );
}
