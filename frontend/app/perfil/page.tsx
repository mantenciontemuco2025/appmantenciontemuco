"use client";

import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ImagePlus, Loader2, LockKeyhole, Mail, ShieldCheck, Trash2, UserRound, CalendarDays, MapPin } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { setStoredUser, useAuth } from "@/lib/auth";
import { signatureImageUrl } from "@/lib/signatures";
import type { UserRole } from "@/lib/types";
import { PageLoading } from "@/components/ui/page-loading";

const ALLOWED_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const MAX_SIZE_BYTES = 2 * 1024 * 1024;

function roleLabel(role: UserRole): string {
  return role === "ADMIN" ? "Administrador" : role === "SUPERVISOR" ? "Supervisor" : "Trabajador";
}

function formatDate(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("es-CL", { year: "numeric", month: "long", day: "numeric" });
}

export default function ProfilePage() {
  const { user, loading, logout, setUser } = useAuth();
  const router = useRouter();
  const [signature, setSignature] = useState<string | null>(null);
  const [message, setMessage] = useState<{ variant: "success" | "error"; text: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [changingPassword, setChangingPassword] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState<{ variant: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);

  useEffect(() => {
    setSignature(user?.signature ?? null);
  }, [user?.signature]);

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !user) return;

    if (!ALLOWED_TYPES.has(file.type)) {
      setMessage({ variant: "error", text: "Seleccione una imagen PNG, JPEG o WebP." });
      return;
    }
    if (file.size > MAX_SIZE_BYTES) {
      setMessage({ variant: "error", text: "La imagen no puede superar 2 MB." });
      return;
    }

    setUploading(true);
    setMessage(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await api.upload<{ url: string }>("/api/users/me/signature", form);
      const updated = { ...user, signature: result.url };
      setSignature(result.url);
      setUser(updated);
      setStoredUser(updated);
      setMessage({ variant: "success", text: "Firma guardada. Se usará al emitir o aprobar nuevas OTs." });
    } catch (error) {
      setMessage({ variant: "error", text: error instanceof Error ? error.message : "No se pudo guardar la firma." });
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete() {
    if (!user) return;
    setRemoving(true);
    setMessage(null);
    try {
      await api.del("/api/users/me/signature");
      const updated = { ...user, signature: null };
      setSignature(null);
      setUser(updated);
      setStoredUser(updated);
      setMessage({ variant: "success", text: "La firma se quitó de su perfil. Las OTs ya firmadas conservan su registro histórico." });
    } catch (error) {
      setMessage({ variant: "error", text: error instanceof Error ? error.message : "No se pudo eliminar la firma." });
    } finally {
      setRemoving(false);
    }
  }

  async function handleChangePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      setPasswordMessage({ variant: "error", text: "Las contraseñas nuevas no coinciden." });
      return;
    }
    setChangingPassword(true);
    setPasswordMessage(null);
    try {
      await api.post<void>("/api/users/me/password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordMessage({ variant: "success", text: "Contraseña actualizada correctamente." });
    } catch (error) {
      setPasswordMessage({ variant: "error", text: error instanceof Error ? error.message : "No se pudo cambiar la contraseña." });
    } finally {
      setChangingPassword(false);
    }
  }

  if (loading || !user) {
    return <PageLoading message={loading ? "Validando sesión..." : "Redirigiendo al inicio de sesión..."} />;
  }

  return (
    <Shell fullName={user.full_name} role={user.role} onLogout={logout}>
      <div className="mb-5">
        <h1 className="text-2xl font-bold">Mi perfil</h1>
        <p className="text-muted-foreground">
          {user.role === "SUPERVISOR"
            ? "Su información personal y área supervisada."
            : "Su información personal y su firma manuscrita para autorizar OTs."}
        </p>
      </div>

      {/* ── Información personal ─────────────────────────────────────────── */}
      <Card className="mb-6 max-w-2xl">
        <CardHeader>
          <CardTitle className="text-lg">Información personal</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-3">
            <li className="flex items-start gap-3">
              <UserRound className="mt-0.5 h-4 w-4 text-muted-foreground shrink-0" />
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground">Nombre completo</p>
                <p className="font-medium">{user.full_name}</p>
              </div>
            </li>
            <li className="flex items-start gap-3">
              <Mail className="mt-0.5 h-4 w-4 text-muted-foreground shrink-0" />
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground">Correo electrónico</p>
                <p className="font-medium break-all">{user.email}</p>
              </div>
            </li>
            <li className="flex items-start gap-3">
              <ShieldCheck className="mt-0.5 h-4 w-4 text-muted-foreground shrink-0" />
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground">Rol</p>
                <p className="font-medium">{roleLabel(user.role)}</p>
              </div>
            </li>
            {user.role === "SUPERVISOR" && (
              <li className="flex items-start gap-3">
                <MapPin className="mt-0.5 h-4 w-4 text-muted-foreground shrink-0" />
                <div className="min-w-0">
                  <p className="text-xs text-muted-foreground">Sección supervisada</p>
                  <p className="font-medium">{user.area_name || "Sin sección asignada"}</p>
                </div>
              </li>
            )}
            <li className="flex items-start gap-3">
              <CalendarDays className="mt-0.5 h-4 w-4 text-muted-foreground shrink-0" />
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground">Miembro desde</p>
                <p className="font-medium">{formatDate(user.created_at)}</p>
              </div>
            </li>
          </ul>
        </CardContent>
      </Card>

      <Card className="mb-6 max-w-2xl">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <LockKeyhole className="h-5 w-5" /> Cambiar contraseña
          </CardTitle>
        </CardHeader>
        <CardContent>
          {passwordMessage && <InlineAlert variant={passwordMessage.variant}>{passwordMessage.text}</InlineAlert>}
          <form onSubmit={handleChangePassword} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="current-password" className="text-sm font-medium">Contraseña actual</label>
              <Input id="current-password" type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required autoComplete="current-password" />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="new-password" className="text-sm font-medium">Nueva contraseña</label>
              <Input id="new-password" type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} minLength={6} required autoComplete="new-password" />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="confirm-password" className="text-sm font-medium">Repetir nueva contraseña</label>
              <Input id="confirm-password" type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} minLength={6} required autoComplete="new-password" />
            </div>
            <Button type="submit" disabled={changingPassword}>
              {changingPassword && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Guardar nueva contraseña
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* ── Firma manuscrita: solo administradores y trabajadores ───────── */}
      {user.role !== "SUPERVISOR" && (
      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle className="text-lg">Firma manuscrita</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {message && <InlineAlert variant={message.variant}>{message.text}</InlineAlert>}

          {signature ? (
            <div className="rounded-lg border bg-white p-4">
              <p className="mb-3 text-sm font-medium">Firma actual</p>
              <img
                src={signatureImageUrl(signature)}
                alt={`Firma de ${user.full_name}`}
                className="h-28 w-full rounded border object-contain"
              />
            </div>
          ) : (
            <InlineAlert variant="warning">
              Aún no tiene una firma cargada. No podrá emitir ni aprobar OTs hasta configurarla.
            </InlineAlert>
          )}

          <div className="space-y-1.5">
            <label htmlFor="signature-file" className="text-sm font-medium">Imagen de firma</label>
            <Input
              id="signature-file"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={handleUpload}
              disabled={uploading || removing}
            />
            <p className="text-xs text-muted-foreground">PNG, JPEG o WebP, hasta 2 MB. Use fondo blanco o transparente.</p>
          </div>

          <div className="flex flex-col gap-2 sm:flex-row">
            <label
              htmlFor="signature-file"
              className={`inline-flex h-10 flex-1 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground ${uploading || removing ? "pointer-events-none opacity-50" : "cursor-pointer hover:bg-primary/90"}`}
            >
              {uploading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <ImagePlus className="mr-2 h-4 w-4" />}
              {signature ? "Reemplazar firma" : "Seleccionar firma"}
            </label>
            {signature && (
              <Button variant="outline" className="flex-1" onClick={handleDelete} disabled={uploading || removing}>
                {removing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                Quitar del perfil
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
      )}
    </Shell>
  );
}
