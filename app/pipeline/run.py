"""Run the pipeline on one image.

    preprocess -> RapidOCR -> extract -> validate
        └─ problems (or forced) -> VLM OCR -> extract -> validate -> reconcile
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.llm.client import LLMError
from app.pipeline.extract import extract
from app.pipeline.ocr_rapid import OcrResult, run_ocr
from app.pipeline.ocr_vlm import run_vlm
from app.pipeline.preprocess import Preprocessed, preprocess
from app.pipeline.reconcile import reconcile
from app.pipeline.validate import NUMBER_WARNINGS, ReceiptWarning, Validated, validate
from app.schemas import ReceiptData

# Warnings that make a second (VLM) reading worthwhile in "auto" mode.
VLM_TRIGGERS = NUMBER_WARNINGS | {"LOW_OCR_CONFIDENCE", "BAD_DATE"}


@dataclass
class PipelineResult:
    receipt: ReceiptData
    warnings: list[ReceiptWarning]
    status: str                      # verified | needs_review
    prep: Preprocessed
    ocr: OcrResult
    extraction_raw: str
    dropped_items: list[str]
    notes: list[str]
    timings: dict[str, float]
    models: dict[str, str]
    llm_stats: dict = field(default_factory=dict)
    ocr_text_vlm: str | None = None
    source: str = "rapid"            # which reading the stored data comes from: rapid | vlm

    def to_dict(self) -> dict:
        """JSON-friendly summary (also the prediction format used by eval/run_eval.py)."""
        return {
            **self.receipt.model_dump(),
            "status": self.status,
            "warnings": [w.to_dict() for w in self.warnings],
            "dropped_items": self.dropped_items,
            "notes": self.notes,
            "source": self.source,
            "ocr_text": self.ocr.text,
            "ocr_text_vlm": self.ocr_text_vlm,
            "ocr_confidence": self.ocr.mean_confidence,
            "preprocess": {
                "crop_method": self.prep.crop_method,
                "receipt_fraction": self.prep.receipt_fraction,
                "quality_warnings": self.prep.quality.warnings,
            },
            "timings": self.timings,
            "models": self.models,
            "llm_stats": self.llm_stats,
        }


def needs_second_reading(validated: Validated, *, force: bool = False) -> bool:
    mode = get_settings().vlm_mode
    if force or mode == "always":
        return True
    if mode == "never":
        return False
    return any(w.code in VLM_TRIGGERS for w in validated.warnings)


def process_image(source: str | Path | bytes | np.ndarray,
                  on_stage: Callable[[str], None] | None = None, *, force_vlm: bool = False) -> PipelineResult:
    """``on_stage`` is called as each stage starts: preprocess, ocr, extract, validate,
    and (when a second reading runs) vlm, vlm_extract."""
    settings = get_settings()
    stage = on_stage or (lambda _name: None)
    started = time.perf_counter()
    timings: dict[str, float] = {}

    def timed(name: str, fn, *args, **kwargs):
        t = time.perf_counter()
        value = fn(*args, **kwargs)
        timings[f"{name}_s"] = round(time.perf_counter() - t, 2)
        return value

    stage("preprocess")
    prep = timed("preprocess", preprocess, source)
    stage("ocr")
    ocr = timed("ocr", run_ocr, prep.for_ocr)

    stage("extract")
    extraction = timed("extract", extract, ocr.text)
    stage("validate")
    checks = dict(ocr_confidence=ocr.mean_confidence, image_warnings=prep.quality.warnings)
    first = validate(extraction.receipt, ocr_text=ocr.text, **checks)

    chosen, source, raw, notes, extra = first, "rapid", extraction.raw, [], []
    models = {"ocr": ocr.engine, "extract": settings.extract_model}
    vlm_text = None

    if needs_second_reading(first, force=force_vlm):
        try:
            stage("vlm")
            vlm = timed("vlm", run_vlm, prep.for_vlm)
            vlm_text = vlm.text
            models["vlm"] = vlm.engine
            stage("vlm_extract")
            extraction2 = timed("extract2", extract, vlm.text)
        except (LLMError, ValueError) as error:
            notes.append(f"Second reading (VLM) failed, first reading kept: {error}")
        else:
            # A number printed according to either reading counts as printed.
            both = f"{ocr.text}\n{vlm.text}"
            first = validate(extraction.receipt, ocr_text=both, **checks)
            second = validate(extraction2.receipt, ocr_text=both, image_warnings=prep.quality.warnings)
            choice = reconcile(first, second)
            chosen, source, notes, extra = choice.chosen, choice.source, choice.notes, choice.extra_warnings
            if source == "vlm":
                raw = extraction2.raw

    warnings = [*chosen.warnings, *extra]
    timings["total_s"] = round(time.perf_counter() - started, 2)
    return PipelineResult(
        receipt=chosen.receipt,
        warnings=warnings,
        status="needs_review" if warnings else "verified",
        prep=prep,
        ocr=ocr,
        extraction_raw=raw,
        dropped_items=chosen.dropped_items,
        notes=[*chosen.notes, *notes],
        timings=timings,
        models=models,
        llm_stats=extraction.stats,
        ocr_text_vlm=vlm_text,
        source=source,
    )
