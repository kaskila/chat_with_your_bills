"""Image preprocessing for OCR.

RapidOCR and the VLM are neural networks trained on ordinary photos, so this
module does *not* binarize, boost contrast or upscale (that lost values in the
2026-10-09 experiment, see docs/IMPLEMENTATION_PLAN.md, Phase 1). It only:

1. loads the photo with its EXIF orientation applied,
2. measures image quality (blur, brightness, resolution) and warns,
3. finds the receipt (bright, colourless region; edge fallback),
4. crops and straightens it (perspective warp or rotated rectangle),
5. resizes it (downscale only) for each OCR engine.

Optional shadow removal / contrast stretch exist for experiments and are off by
default.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from app.config import get_settings

# Work on a small copy when searching for the receipt; it is fast and robust.
_DETECT_SIDE = 800

# Quality thresholds (measured on a copy scaled to 1000 px longest side).
BLUR_MIN_VARIANCE = 60.0
DARK_MAX_MEAN = 70.0
# Share of pure-white (blown-out) pixels. Clean receipts are bright (mean ~240) but
# have few clipped pixels (<10%); a washed-out photo has many.
CLIPPED_MAX_SHARE = 0.25
LOW_RES_MIN_SIDE = 500


@dataclass
class Quality:
    blur_variance: float
    brightness: float
    width: int
    height: int
    warnings: list[str] = field(default_factory=list)


@dataclass
class Preprocessed:
    original: np.ndarray            # BGR, orientation fixed
    cropped: np.ndarray             # BGR, receipt only, upright
    for_ocr: np.ndarray             # full photo (or crop, see rapid_use_crop), limited to rapid_max_side
    for_vlm: np.ndarray             # cropped, limited to vlm_max_side
    crop_method: str                # perspective | rotated_rect | none
    receipt_fraction: float         # receipt area / photo area (1.0 if not found)
    rotation_deg: float             # rotation applied while straightening
    quality: Quality
    seconds: float


# --------------------------------------------------------------------------
# Loading and quality
# --------------------------------------------------------------------------

def load_image(source: str | Path | bytes) -> np.ndarray:
    """Read a photo as BGR. OpenCV applies the EXIF orientation by default."""
    if isinstance(source, (bytes, bytearray)):
        data = np.frombuffer(source, dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    else:
        # np.fromfile + imdecode also works with non-ASCII Windows paths.
        image = cv2.imdecode(np.fromfile(str(source), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not read the image (unsupported or corrupt file).")
    return image


def resize_max_side(image: np.ndarray, max_side: int) -> np.ndarray:
    """Downscale so the longest side is at most ``max_side``. Never upscales."""
    h, w = image.shape[:2]
    scale = max_side / max(h, w)
    if scale >= 1:
        return image
    return cv2.resize(image, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)


def assess_quality(image: np.ndarray) -> Quality:
    h, w = image.shape[:2]
    gray = cv2.cvtColor(resize_max_side(image, 1000), cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    warnings = []
    if blur < BLUR_MIN_VARIANCE:
        warnings.append("BLURRY")
    if brightness < DARK_MAX_MEAN:
        warnings.append("TOO_DARK")
    elif float(np.mean(gray >= 255)) > CLIPPED_MAX_SHARE:
        warnings.append("OVEREXPOSED")
    if min(h, w) < LOW_RES_MIN_SIDE:
        warnings.append("LOW_RESOLUTION")
    return Quality(round(blur, 1), round(brightness, 1), w, h, warnings)


# --------------------------------------------------------------------------
# Finding the receipt
# --------------------------------------------------------------------------

def _receipt_mask(small: np.ndarray) -> np.ndarray:
    """Bright, low-saturation pixels: receipt paper on a darker or coloured background."""
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    sat, val = hsv[..., 1], hsv[..., 2]
    # Brightness threshold chosen per photo (Otsu), but never below 110.
    otsu, _ = cv2.threshold(val, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = ((val > max(110.0, otsu)) & (sat < 70)).astype(np.uint8) * 255
    # A small close joins broken paper; filling contours then fills the holes left
    # by printed text without growing outward (a large close would bridge the gap
    # to nearby white objects, e.g. a laptop next to the receipt).
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    mask = _fill_holes(mask)
    # Open removes thin bridges and specks; fill again afterwards.
    k = max(5, round(min(small.shape[:2]) * 0.03)) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return _fill_holes(mask)


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    filled = np.zeros_like(mask)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    return filled


def _edge_mask(small: np.ndarray) -> np.ndarray:
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    return _fill_holes(cv2.dilate(edges, kernel, iterations=2))


def _largest_contour(mask: np.ndarray, min_fraction: float) -> np.ndarray | None:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < min_fraction * mask.shape[0] * mask.shape[1]:
        return None
    return contour


def find_receipt(image: np.ndarray, min_fraction: float | None = None) -> np.ndarray | None:
    """Return the receipt outline in full-image coordinates, or None."""
    min_fraction = get_settings().min_receipt_area if min_fraction is None else min_fraction
    small = resize_max_side(image, _DETECT_SIDE)
    scale = image.shape[1] / small.shape[1]
    contour = _largest_contour(_receipt_mask(small), min_fraction)
    if contour is None:
        contour = _largest_contour(_edge_mask(small), min_fraction)
    if contour is None:
        return None
    return (contour.astype(np.float32) * scale)


# --------------------------------------------------------------------------
# Cropping and straightening
# --------------------------------------------------------------------------

def _order_corners(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as top-left, top-right, bottom-right, bottom-left."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], dtype=np.float32)


def _quad(contour: np.ndarray) -> np.ndarray | None:
    """4 corners if the outline is a clean quadrilateral (flat, uncrumpled receipt)."""
    hull = cv2.convexHull(contour)
    approx = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True)
    if len(approx) != 4 or not cv2.isContourConvex(approx):
        return None
    # The quad must explain the shape well, otherwise a rotated rectangle is safer.
    if cv2.contourArea(approx) > 1.15 * cv2.contourArea(contour):
        return None
    return approx


def _warp_perspective(image: np.ndarray, quad: np.ndarray, pad: int) -> np.ndarray:
    tl, tr, br, bl = _order_corners(quad)
    width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))) + 2 * pad
    height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))) + 2 * pad
    target = np.array([[pad, pad], [width - pad, pad], [width - pad, height - pad], [pad, height - pad]],
                      dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl]), target)
    return cv2.warpPerspective(image, matrix, (width, height), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)


def _crop_rotated(image: np.ndarray, contour: np.ndarray, pad: int) -> tuple[np.ndarray, float]:
    """Rotate by the smallest angle that makes the receipt's rectangle upright, then crop it."""
    (cx, cy), (rw, rh), angle = cv2.minAreaRect(contour)
    # The angle range differs between OpenCV versions; bring it into (-45, 45]
    # so the receipt is turned by the smallest amount and keeps its orientation.
    while angle > 45:
        angle -= 90
        rw, rh = rh, rw
    while angle <= -45:
        angle += 90
        rw, rh = rh, rw
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    rotated = cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    x0, y0 = int(max(0, cx - rw / 2 - pad)), int(max(0, cy - rh / 2 - pad))
    x1, y1 = int(min(w, cx + rw / 2 + pad)), int(min(h, cy + rh / 2 + pad))
    return rotated[y0:y1, x0:x1], angle


def crop_receipt(image: np.ndarray) -> tuple[np.ndarray, str, float, float]:
    """Return (cropped image, method, receipt fraction, rotation degrees)."""
    contour = find_receipt(image)
    if contour is None:
        return image, "none", 1.0, 0.0
    fraction = cv2.contourArea(contour) / (image.shape[0] * image.shape[1])
    pad = max(8, round(min(image.shape[:2]) * 0.01))
    quad = _quad(contour)
    if quad is not None:
        return _warp_perspective(image, quad, pad), "perspective", fraction, 0.0
    cropped, angle = _crop_rotated(image, contour, pad)
    return cropped, "rotated_rect", fraction, angle


# --------------------------------------------------------------------------
# Optional corrections (off by default; kept only if the eval shows a gain)
# --------------------------------------------------------------------------

def remove_shadows(image: np.ndarray) -> np.ndarray:
    """Divide each channel by its blurred background to flatten uneven lighting."""
    k = max(21, (min(image.shape[:2]) // 15) | 1)
    out = []
    for channel in cv2.split(image):
        background = cv2.medianBlur(cv2.dilate(channel, np.ones((7, 7), np.uint8)), k)
        out.append(cv2.divide(channel, background, scale=255))
    return cv2.merge(out)


def stretch_contrast(image: np.ndarray) -> np.ndarray:
    """Linear stretch between the 1st and 99th brightness percentiles."""
    low, high = np.percentile(image, (1, 99))
    if high - low < 1:
        return image
    return np.clip((image.astype(np.float32) - low) * 255.0 / (high - low), 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def preprocess(source: str | Path | bytes | np.ndarray, *, crop: bool | None = None,
               ocr_on_crop: bool | None = None, shadows: bool | None = None,
               contrast: bool = False) -> Preprocessed:
    """``crop``: find and crop the receipt (default: settings.crop_receipt).
    ``ocr_on_crop``: give RapidOCR the crop instead of the full photo (default: settings.rapid_use_crop)."""
    settings = get_settings()
    crop = settings.crop_receipt if crop is None else crop
    ocr_on_crop = settings.rapid_use_crop if ocr_on_crop is None else ocr_on_crop
    shadows = settings.rapid_remove_shadows if shadows is None else shadows
    started = time.perf_counter()
    original = source if isinstance(source, np.ndarray) else load_image(source)
    quality = assess_quality(original)

    if crop:
        cropped, method, fraction, rotation = crop_receipt(original)
    else:
        cropped, method, fraction, rotation = original, "none", 1.0, 0.0

    ocr_input = cropped if ocr_on_crop else original
    if shadows:
        cropped, ocr_input = remove_shadows(cropped), remove_shadows(ocr_input)
    if contrast:
        cropped, ocr_input = stretch_contrast(cropped), stretch_contrast(ocr_input)

    return Preprocessed(
        original=original,
        cropped=cropped,
        for_ocr=resize_max_side(ocr_input, settings.rapid_max_side),
        for_vlm=resize_max_side(cropped, settings.vlm_max_side),
        crop_method=method,
        receipt_fraction=round(float(fraction), 3),
        rotation_deg=round(float(rotation), 2),
        quality=quality,
        seconds=round(time.perf_counter() - started, 3),
    )
