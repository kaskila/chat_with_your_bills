// Shrink large photos in the browser before uploading: a 4080 x 3072 phone photo (1.5-3 MB)
// becomes about 2400 x 1800 (a few hundred KB), much faster on mobile data. The pipeline
// never uses more than 1600 px for OCR (896 px for the vision model), so nothing is lost.
// The browser applies the photo's EXIF rotation when drawing, so the result is upright.

export const MAX_SIDE = 2400;
const QUALITY = 0.9;
const TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

/** Returns a smaller JPEG File, or the original when it is already small (or anything fails). */
export async function shrinkPhoto(file) {
  if (!TYPES.has(file.type) || typeof createImageBitmap !== "function") return file;
  let bitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    return file; // unreadable here: let the server decide
  }
  try {
    const scale = MAX_SIDE / Math.max(bitmap.width, bitmap.height);
    if (scale >= 1) return file; // small already: keep the original bytes
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const context = canvas.getContext("2d");
    context.imageSmoothingQuality = "high";
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", QUALITY));
    if (!blob || blob.size >= file.size) return file;
    const name = file.name.replace(/\.[^.]+$/, "") + ".jpg";
    return new File([blob], name, { type: "image/jpeg", lastModified: file.lastModified });
  } finally {
    bitmap.close();
  }
}
