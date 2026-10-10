"""Pipeline Lab: run single stages on an image or text, for testing and tuning.

These run in the request (not the job queue) and can take a while: OCR a few
seconds, extraction ~30-60 s on CPU.
"""

import base64
import time
from typing import Literal

import cv2
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.llm.client import LLMError
from app.pipeline.extract import extract
from app.pipeline.ocr_rapid import run_ocr
from app.pipeline.ocr_vlm import run_vlm
from app.pipeline.preprocess import preprocess
from app.pipeline.validate import validate

router = APIRouter(prefix="/api/lab", tags=["lab"])


def _jpeg_b64(image) -> str:
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buffer.tobytes()).decode() if ok else ""


async def _read_image(file: UploadFile):
    data = await file.read()
    try:
        return await run_in_threadpool(preprocess, data)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.post("/preprocess")
async def lab_preprocess(file: UploadFile = File(...)) -> dict:
    prep = await _read_image(file)
    return {
        "crop_method": prep.crop_method, "receipt_fraction": prep.receipt_fraction,
        "rotation_deg": prep.rotation_deg, "seconds": prep.seconds,
        "quality": {"blur_variance": prep.quality.blur_variance, "brightness": prep.quality.brightness,
                    "width": prep.quality.width, "height": prep.quality.height,
                    "warnings": prep.quality.warnings},
        "cropped_jpeg_base64": _jpeg_b64(prep.cropped),
        "cropped_size": [int(prep.cropped.shape[1]), int(prep.cropped.shape[0])],
    }


@router.post("/ocr")
async def lab_ocr(file: UploadFile = File(...), engine: Literal["rapid", "vlm"] = "rapid") -> dict:
    prep = await _read_image(file)
    if engine == "vlm":
        try:
            vlm = await run_in_threadpool(run_vlm, prep.for_vlm)
        except LLMError as error:
            raise HTTPException(503, str(error)) from error
        return {"text": vlm.text, "seconds": vlm.seconds, "engine": vlm.engine, "lines": [],
                "image_size": list(vlm.image_size), "image_jpeg_base64": _jpeg_b64(prep.for_vlm)}
    result = await run_in_threadpool(run_ocr, prep.for_ocr)
    h, w = prep.for_ocr.shape[:2]
    return {**result.to_dict(), "image_size": [int(w), int(h)],
            "image_jpeg_base64": _jpeg_b64(prep.for_ocr)}


class ExtractRequest(BaseModel):
    text: str
    ocr_confidence: float | None = None


@router.post("/extract")
async def lab_extract(body: ExtractRequest) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "Text is empty.")
    started = time.perf_counter()
    try:
        extraction = await run_in_threadpool(extract, body.text)
    except LLMError as error:
        raise HTTPException(503, str(error)) from error
    validated = validate(extraction.receipt, ocr_text=body.text, ocr_confidence=body.ocr_confidence)
    return {
        "receipt": validated.receipt.model_dump(),
        "status": validated.status,
        "warnings": [w.to_dict() for w in validated.warnings],
        "notes": validated.notes,
        "dropped_items": validated.dropped_items,
        "raw": extraction.raw,
        "llm_stats": extraction.stats,
        "seconds": round(time.perf_counter() - started, 2),
    }
