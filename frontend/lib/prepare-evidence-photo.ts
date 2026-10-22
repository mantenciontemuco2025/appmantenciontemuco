const MAX_EDGE = 1920;
const MAX_OUTPUT_BYTES = 4 * 1024 * 1024;
const MAX_SOURCE_PIXELS = 100_000_000;
const MAX_DIRECT_UPLOAD_BYTES = 12 * 1024 * 1024;
const DIRECT_UPLOAD_MIMES = new Set(["image/jpeg", "image/png", "image/webp"]);

function isHeif(file: File) {
  return /\.(heic|heif)$/i.test(file.name) || /image\/(heic|heif)/i.test(file.type);
}

async function decodeImage(blob: Blob) {
  if (typeof createImageBitmap === "function") {
    try {
      const bitmap = await createImageBitmap(blob);
      return {
        image: bitmap as CanvasImageSource,
        width: bitmap.width,
        height: bitmap.height,
        close: () => bitmap.close(),
      };
    } catch {
      // Fall through to the browser's regular image decoder.
    }
  }

  const objectUrl = URL.createObjectURL(blob);
  try {
    const image = new Image();
    image.src = objectUrl;
    await image.decode();
    return {
      image: image as CanvasImageSource,
      width: image.naturalWidth,
      height: image.naturalHeight,
      close: () => URL.revokeObjectURL(objectUrl),
    };
  } catch (error) {
    URL.revokeObjectURL(objectUrl);
    throw error;
  }
}

function canvasBlob(canvas: HTMLCanvasElement, quality: number) {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error("No se pudo preparar la imagen.")),
      "image/jpeg",
      quality,
    );
  });
}

/** Converts browser-supported photos (including HEIC/HEIF) into a small JPEG. */
export async function prepareEvidencePhoto(file: File): Promise<File> {
  if (!file.type.startsWith("image/") && !isHeif(file)) {
    throw new Error("El archivo seleccionado no parece ser una imagen.");
  }

  // Keep the previous upload path for ordinary photos and screenshots. The API
  // already validates and normalizes these formats, while decoding every image
  // in the phone's PWA can fail or consume excessive memory on Android.
  if (DIRECT_UPLOAD_MIMES.has(file.type) && file.size <= MAX_DIRECT_UPLOAD_BYTES) {
    return file;
  }

  let source: Blob = file;
  if (isHeif(file)) {
    try {
      const { default: heic2any } = await import("heic2any");
      const converted = await heic2any({ blob: file, toType: "image/jpeg", quality: 0.86 });
      source = Array.isArray(converted) ? converted[0] : converted;
    } catch {
      throw new Error("No se pudo leer esta foto HEIC/HEIF. Ábrela y compártela como JPG.");
    }
  }

  let decoded: Awaited<ReturnType<typeof decodeImage>>;
  try {
    decoded = await decodeImage(source);
  } catch {
    throw new Error("No se pudo leer esta foto. Prueba guardándola como JPG, PNG o HEIC.");
  }

  try {
    const { width, height } = decoded;
    if (!width || !height || width * height > MAX_SOURCE_PIXELS) {
      throw new Error("La resolución de la foto es demasiado grande para procesarla en este teléfono.");
    }

    const initialScale = Math.min(1, MAX_EDGE / Math.max(width, height));
    let scale = initialScale;
    let result: Blob | null = null;

    for (let attempt = 0; attempt < 7; attempt += 1) {
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(width * scale));
      canvas.height = Math.max(1, Math.round(height * scale));
      const context = canvas.getContext("2d", { alpha: false });
      if (!context) throw new Error("Este navegador no pudo preparar la foto.");
      context.drawImage(decoded.image, 0, 0, canvas.width, canvas.height);

      for (const quality of [0.82, 0.72, 0.62]) {
        result = await canvasBlob(canvas, quality);
        if (result.size <= MAX_OUTPUT_BYTES) break;
      }
      canvas.width = 1;
      canvas.height = 1;
      if (result && result.size <= MAX_OUTPUT_BYTES) break;
      scale *= 0.8;
    }

    if (!result || result.size > MAX_OUTPUT_BYTES) {
      throw new Error("Esta foto no se pudo reducir lo suficiente. Prueba recortándola o eligiendo otra versión.");
    }
    const safeName = file.name.replace(/\.[^.]+$/, "") || "evidencia";
    return new File([result], `${safeName}.jpg`, {
      type: "image/jpeg",
      lastModified: file.lastModified || Date.now(),
    });
  } finally {
    decoded.close();
  }
}
