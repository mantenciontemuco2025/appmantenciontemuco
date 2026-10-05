"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Expand, ImagePlus, Loader2, Camera, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";
import { MAX_EVIDENCE_PHOTOS_PER_USER } from "@/lib/evidence";
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

function EvidencePhoto({
  woId,
  item,
  canDelete,
  deleting,
  onDelete,
  onOpen,
  onUrlReady,
}: {
  woId: number;
  item: EvidenceItem;
  canDelete: boolean;
  deleting: boolean;
  onDelete: () => void;
  onOpen: () => void;
  onUrlReady: (itemId: number, url: string | null) => void;
}) {
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
        onUrlReady(item.id, objectUrl);
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
      onUrlReady(item.id, null);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [woId, item.id, onUrlReady]);

  return (
    <figure className="overflow-hidden rounded-lg border bg-background">
      <div className="flex aspect-video items-center justify-center bg-muted">
        {url ? (
          <button
            type="button"
            className="group relative h-full w-full cursor-zoom-in overflow-hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary"
            onClick={onOpen}
            aria-label={`Ampliar foto ${item.filename}`}
          >
            {/* The authenticated API returns a temporary object URL, not a public Drive link. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={url} alt={item.filename} className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-[1.02]" />
            <span className="absolute bottom-2 right-2 inline-flex items-center rounded-md bg-black/65 px-2 py-1 text-xs font-medium text-white opacity-90 transition-opacity group-hover:opacity-100">
              <Expand className="mr-1 h-3.5 w-3.5" /> Ampliar
            </span>
          </button>
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
        {canDelete && (
          <button
            type="button"
            className="mt-2 inline-flex h-8 items-center rounded-md border border-destructive/40 px-2.5 text-xs font-medium text-destructive hover:bg-destructive/10 disabled:opacity-60"
            disabled={deleting}
            onClick={onDelete}
          >
            {deleting ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="mr-1.5 h-3.5 w-3.5" />
            )}
            {deleting ? "Eliminando…" : "Eliminar foto"}
          </button>
        )}
      </figcaption>
    </figure>
  );
}

export function WorkOrderEvidencePanel({
  woId,
  stage,
  canUpload,
  currentUserId,
  canDeleteAny,
}: {
  woId: number;
  stage: EvidenceStage;
  canUpload: boolean;
  currentUserId: number;
  canDeleteAny: boolean;
}) {
  const [items, setItems] = useState<EvidenceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [photoUrls, setPhotoUrls] = useState<Record<number, string>>({});
  const [viewerItemId, setViewerItemId] = useState<number | null>(null);

  const registerPhotoUrl = useCallback((itemId: number, url: string | null) => {
    setPhotoUrls((current) => {
      if (url) return current[itemId] === url ? current : { ...current, [itemId]: url };
      if (!(itemId in current)) return current;
      const next = { ...current };
      delete next[itemId];
      return next;
    });
  }, []);

  const moveViewer = useCallback((direction: -1 | 1) => {
    setViewerItemId((currentId) => {
      if (currentId === null || items.length < 2) return currentId;
      const currentIndex = items.findIndex((item) => item.id === currentId);
      if (currentIndex < 0) return items[0]?.id ?? null;
      const nextIndex = (currentIndex + direction + items.length) % items.length;
      return items[nextIndex].id;
    });
  }, [items]);

  useEffect(() => {
    if (viewerItemId === null) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setViewerItemId(null);
      if (event.key === "ArrowLeft") moveViewer(-1);
      if (event.key === "ArrowRight") moveViewer(1);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [moveViewer, viewerItemId]);

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
    const available = Math.max(0, MAX_EVIDENCE_PHOTOS_PER_USER - ownCount);
    const selected = Array.from(files).slice(0, available);
    if (selected.length < files.length) {
      setMessage(`Cada usuario puede subir hasta ${MAX_EVIDENCE_PHOTOS_PER_USER} fotos por OT; te quedan ${available} espacio(s).`);
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

  async function handleDelete(item: EvidenceItem) {
    if (!window.confirm(`¿Eliminar la foto "${item.filename}"? Esta acción no se puede deshacer.`)) return;

    setDeletingId(item.id);
    setMessage(null);
    try {
      await api.del<void>(`/api/work-orders/${woId}/evidence/${item.id}`);
      setItems((current) => current.filter((currentItem) => currentItem.id !== item.id));
      setViewerItemId((current) => current === item.id ? null : current);
      setMessage("Foto eliminada correctamente.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo eliminar la foto.");
    } finally {
      setDeletingId(null);
    }
  }

  const ownCount = items.filter((item) => item.uploaded_by_user_id === currentUserId).length;
  const available = Math.max(0, MAX_EVIDENCE_PHOTOS_PER_USER - ownCount);
  const viewerItem = items.find((item) => item.id === viewerItemId) ?? null;
  const viewerUrl = viewerItem ? photoUrls[viewerItem.id] : null;
  return (
    <>
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
              {" "}Cada usuario puede subir hasta {MAX_EVIDENCE_PHOTOS_PER_USER} fotos por OT. Todos los autorizados a ver la OT pueden verlas; se guardan privadas en Drive y se comprimen automáticamente.
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
            {items.map((item) => (
              <EvidencePhoto
                key={item.id}
                woId={woId}
                item={item}
                canDelete={canDeleteAny || (canUpload && item.uploaded_by_user_id === currentUserId)}
                deleting={deletingId === item.id}
                onDelete={() => void handleDelete(item)}
                onOpen={() => setViewerItemId(item.id)}
                onUrlReady={registerPhotoUrl}
              />
            ))}
          </div>
        ) : (
          <p className="py-2 text-sm text-muted-foreground">Todavía no hay fotos adjuntas.</p>
        )}
        </CardContent>
      </Card>

      {viewerItem && viewerUrl ? (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/85 p-3 backdrop-blur-sm sm:p-6"
          role="dialog"
          aria-modal="true"
          aria-label={`Visualizador de ${viewerItem.filename}`}
          onClick={() => setViewerItemId(null)}
        >
          <div className="relative flex max-h-full w-full max-w-6xl flex-col" onClick={(event) => event.stopPropagation()}>
            <div className="mb-3 flex items-center justify-between gap-3 text-white">
              <div className="min-w-0">
                <p className="truncate font-semibold">{viewerItem.filename}</p>
                <p className="truncate text-xs text-white/75">
                  {viewerItem.stage === "ISSUE" ? "Emisión" : "Trabajo realizado"} · {viewerItem.uploaded_by_name}
                </p>
              </div>
              <button
                type="button"
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/15 text-white hover:bg-white/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
                onClick={() => setViewerItemId(null)}
                aria-label="Cerrar visualizador"
              >
                <X className="h-6 w-6" />
              </button>
            </div>

            <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden rounded-xl bg-black/40">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={viewerUrl} alt={viewerItem.filename} className="max-h-[78vh] max-w-full object-contain" />
              {items.length > 1 ? (
                <>
                  <button
                    type="button"
                    className="absolute left-2 inline-flex h-11 w-11 items-center justify-center rounded-full bg-black/55 text-white hover:bg-black/75 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white sm:left-4"
                    onClick={() => moveViewer(-1)}
                    aria-label="Ver foto anterior"
                  >
                    <ChevronLeft className="h-7 w-7" />
                  </button>
                  <button
                    type="button"
                    className="absolute right-2 inline-flex h-11 w-11 items-center justify-center rounded-full bg-black/55 text-white hover:bg-black/75 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white sm:right-4"
                    onClick={() => moveViewer(1)}
                    aria-label="Ver foto siguiente"
                  >
                    <ChevronRight className="h-7 w-7" />
                  </button>
                </>
              ) : null}
            </div>

            <p className="mt-3 text-center text-xs text-white/75">
              {items.findIndex((item) => item.id === viewerItem.id) + 1} de {items.length}
              {items.length > 1 ? " · Usa las flechas para recorrer las fotos" : ""}
            </p>
          </div>
        </div>
      ) : null}
    </>
  );
}
