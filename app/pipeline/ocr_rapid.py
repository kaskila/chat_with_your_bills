"""RapidOCR (PaddleOCR PP-OCR models on onnxruntime/OpenVINO) with reading-order lines."""

import logging
import time
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

from app.config import get_settings

# Text boxes taller than wide by this factor count as "vertical" (sideways photo).
_SIDEWAYS_RATIO = 1.5
# Re-run OCR on a straightened image when text lines tilt more than this.
_DESKEW_MIN_DEG = 3.0


@dataclass
class OcrLine:
    text: str
    confidence: float
    box: tuple[int, int, int, int]  # x0, y0, x1, y1


@dataclass
class OcrResult:
    lines: list[OcrLine]
    text: str
    mean_confidence: float
    seconds: float
    rotation_deg: float  # extra rotation applied here (sideways fix / deskew)
    engine: str

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "mean_confidence": self.mean_confidence,
            "seconds": self.seconds,
            "rotation_deg": self.rotation_deg,
            "engine": self.engine,
            "lines": [{"text": l.text, "confidence": l.confidence, "box": l.box} for l in self.lines],
        }


@dataclass
class _Box:
    text: str
    score: float
    x0: float
    y0: float
    x1: float
    y1: float
    angle: float

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return self.y1 - self.y0


def engine_name(version: str | None = None, model_type: str | None = None, engine: str | None = None) -> str:
    s = get_settings()
    return f"rapidocr/{version or s.rapid_ocr_version}-{model_type or s.rapid_model_type}/{engine or s.rapid_engine}"


@lru_cache(maxsize=4)
def get_engine(version: str | None = None, model_type: str | None = None, engine: str | None = None):
    """Create a RapidOCR engine once per configuration (loading models takes ~1 s)."""
    from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR

    s = get_settings()
    version, model_type, engine = version or s.rapid_ocr_version, model_type or s.rapid_model_type, engine or s.rapid_engine
    params = {
        "Global.log_level": "warning",
        "Det.ocr_version": OCRVersion(version),
        "Rec.ocr_version": OCRVersion(version),
        "Det.model_type": ModelType(model_type),
        "Rec.model_type": ModelType(model_type),
        "Det.engine_type": EngineType(engine),
        "Rec.engine_type": EngineType(engine),
        "Cls.engine_type": EngineType(engine),
        "Det.limit_side_len": s.rapid_det_limit_side_len,
        "Det.limit_type": s.rapid_det_limit_type,
        "Det.box_thresh": s.rapid_box_thresh,
        "Det.unclip_ratio": s.rapid_unclip_ratio,
    }
    if engine == "onnxruntime":
        params["EngineConfig.onnxruntime.intra_op_num_threads"] = s.rapid_threads
    else:
        params["EngineConfig.openvino.inference_num_threads"] = s.rapid_threads
    ocr = RapidOCR(params=params)
    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
    return ocr


def _boxes(raw) -> list[_Box]:
    if raw.boxes is None or raw.txts is None:
        return []
    out = []
    for quad, text, score in zip(raw.boxes, raw.txts, raw.scores):
        quad = np.asarray(quad, dtype=np.float32)
        (x0, y0), (x1, y1) = quad.min(axis=0), quad.max(axis=0)
        dx, dy = quad[1] - quad[0]  # top edge, left -> right
        out.append(_Box(text.strip(), float(score), x0, y0, x1, y1, float(np.degrees(np.arctan2(dy, dx)))))
    return [b for b in out if b.text]


def _v_overlap(a: _Box, b: _Box) -> float:
    """Vertical overlap as a share of the shorter box's height."""
    overlap = min(a.y1, b.y1) - max(a.y0, b.y0)
    return max(0.0, overlap) / max(1.0, min(a.height, b.height))


def _h_collides(a: _Box, b: _Box) -> bool:
    """True if the boxes sit on top of each other horizontally (so they are different lines)."""
    overlap = min(a.x1, b.x1) - max(a.x0, b.x0)
    return overlap > 0.3 * min(a.x1 - a.x0, b.x1 - b.x0)


# Only the most recent rows are candidates; text further up belongs to earlier lines.
_ROW_LOOKBACK = 3


def group_lines(boxes: list[_Box]) -> list[OcrLine]:
    """Group boxes into text lines, each ordered left to right.

    A box joins a line when it overlaps the line vertically by at least half its
    height and does not collide horizontally with a box already in that line.
    """
    rows: list[list[_Box]] = []
    for box in sorted(boxes, key=lambda b: b.yc):
        best, best_overlap = None, 0.5
        for row in rows[-_ROW_LOOKBACK:]:
            if any(_h_collides(box, other) for other in row):
                continue
            overlap = max(_v_overlap(box, other) for other in row)
            if overlap >= best_overlap:
                best, best_overlap = row, overlap
        if best is None:
            rows.append([box])
        else:
            best.append(box)
    rows.sort(key=lambda row: sum(b.yc for b in row) / len(row))

    lines = []
    for row in rows:
        row.sort(key=lambda b: b.x0)
        weights = [len(b.text) for b in row]
        confidence = sum(b.score * w for b, w in zip(row, weights)) / sum(weights)
        lines.append(OcrLine(
            text="  ".join(b.text for b in row),  # two spaces mark a column gap
            confidence=round(confidence, 4),
            box=(int(min(b.x0 for b in row)), int(min(b.y0 for b in row)),
                 int(max(b.x1 for b in row)), int(max(b.y1 for b in row))),
        ))
    return lines


def _quality(boxes: list[_Box]) -> float:
    """How much confidently read text there is; used to compare rotations."""
    return sum(b.score * len(b.text) for b in boxes)


def _is_sideways(boxes: list[_Box]) -> bool:
    long = [b for b in boxes if len(b.text) >= 3]
    if len(long) < 3:
        return False
    vertical = sum((b.y1 - b.y0) > _SIDEWAYS_RATIO * (b.x1 - b.x0) for b in long)
    return vertical > len(long) / 2


def _rotate(image: np.ndarray, degrees: float) -> np.ndarray:
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), degrees, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    matrix[0, 2] += nw / 2 - w / 2
    matrix[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(image, matrix, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def run_ocr(image: np.ndarray, *, version: str | None = None, model_type: str | None = None,
            engine: str | None = None, fix_rotation: bool = True) -> OcrResult:
    ocr = get_engine(version, model_type, engine)
    started = time.perf_counter()
    boxes, rotation = _boxes(ocr(image)), 0.0

    if fix_rotation and _is_sideways(boxes):
        # Photo taken sideways: choose the quarter turn that makes the page upright. RapidOCR's line
        # classifier turns upside-down lines round one by one, so the wrong turn (page upside down)
        # reads almost as well, only with the lines in reverse order (a payment message's balance
        # came before its amount). With the classifier off, only the upright turn reads well
        # (150 vs 46 on that photo), so the turns are compared that way.
        turns = ((cv2.ROTATE_90_CLOCKWISE, -90.0), (cv2.ROTATE_90_COUNTERCLOCKWISE, 90.0))
        upright = max(turns, key=lambda t: _quality(_boxes(ocr(cv2.rotate(image, t[0]), use_cls=False))))
        turned = cv2.rotate(image, upright[0])
        turned_boxes = _boxes(ocr(turned))
        # RapidOCR also reads tall boxes without turning the page, about as well, but sideways lines
        # cannot be put in order (they were joined into one line, bottom line first). So the turned
        # page is used unless it reads far worse.
        if _quality(turned_boxes) >= 0.5 * _quality(boxes):
            boxes, rotation, image = turned_boxes, upright[1], turned

    if fix_rotation and boxes:
        tilt = float(np.median([b.angle for b in boxes if len(b.text) >= 3] or [0.0]))
        if abs(tilt) >= _DESKEW_MIN_DEG:
            straightened = _boxes(ocr(_rotate(image, tilt)))
            if _quality(straightened) > _quality(boxes):
                boxes, rotation = straightened, rotation + tilt

    lines = group_lines(boxes)
    total_chars = sum(len(b.text) for b in boxes)
    mean_conf = sum(b.score * len(b.text) for b in boxes) / total_chars if total_chars else 0.0
    return OcrResult(
        lines=lines,
        text="\n".join(line.text for line in lines),
        mean_confidence=round(mean_conf, 4),
        seconds=round(time.perf_counter() - started, 3),
        rotation_deg=rotation,
        engine=engine_name(version, model_type, engine),
    )
