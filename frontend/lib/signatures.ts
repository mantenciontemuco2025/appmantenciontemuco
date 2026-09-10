const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Return an app-owned image URL for a stored Drive signature.
 *
 * Drive sends a cross-origin policy that blocks direct <img> rendering in
 * Chromium. The backend validates the ID and streams only known signatures.
 */
export function signatureImageUrl(signatureUrl: string): string {
  try {
    const fileId = new URL(signatureUrl).searchParams.get("id");
    if (fileId && /^[a-zA-Z0-9_-]+$/.test(fileId)) {
      return `${API_URL}/api/users/signature-image/${fileId}`;
    }
  } catch {
    // Preserve old/malformed stored values so existing error handling remains
    // visible instead of breaking the page render.
  }
  return signatureUrl;
}
