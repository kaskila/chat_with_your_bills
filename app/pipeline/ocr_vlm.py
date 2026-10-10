"""Second OCR pass with a vision-language model (glm-ocr in Ollama).

Slow on CPU (~15-60 s per receipt at 896 px) but reads layouts RapidOCR + the
text model get wrong, e.g. amounts printed half a line away from their items.
Used only when the first pass fails its checks (see app/pipeline/run.py).

glm-ocr sometimes reads the receipt correctly and then starts over, repeating the
whole text until it runs out of tokens (minutes on CPU). The reply is therefore
streamed and cut as soon as lines start repeating; that also stops generation.
"""

import re
import time
from dataclasses import dataclass

import cv2
import httpx
import numpy as np
import ollama

from app.config import get_settings
from app.llm.client import LLMError
from app.pipeline.preprocess import resize_max_side

# glm-ocr's task prompt for plain text recognition.
_PROMPT = "Text Recognition:"
# Backstop on output length; a long receipt is ~600-900 tokens.
_MAX_TOKENS = 1500
# A repeat of this many consecutive meaningful lines means the model started over.
_REPEAT_WINDOW = 3


@dataclass
class VlmResult:
    text: str
    seconds: float
    engine: str
    image_size: tuple[int, int]
    repetition_cut: bool = False


def _meaningful(line: str) -> str | None:
    """Normalized line, or None for separator/blank lines that legitimately repeat."""
    key = re.sub(r"\s+", " ", line).strip().lower()
    return key if re.search(r"[a-z0-9]", key) else None


def cut_repetition(text: str, window: int = _REPEAT_WINDOW) -> tuple[str, bool]:
    """Cut the text where a run of ``window`` meaningful lines repeats an earlier run."""
    lines = text.split("\n")
    seen: set[tuple[str, ...]] = set()
    recent: list[tuple[int, str]] = []  # (line index, key) of meaningful lines
    for index, line in enumerate(lines):
        key = _meaningful(line)
        if key is None:
            continue
        recent.append((index, key))
        if len(recent) >= window:
            run = tuple(k for _, k in recent[-window:])
            # Identical lines in a row (three of the same item) are legitimate, not a restart.
            if run in seen and len(set(run)) > 1:
                cut_at = recent[-window][0]
                return "\n".join(lines[:cut_at]).rstrip(" -\n"), True
            seen.add(run)
    return text, False


def run_vlm(image: np.ndarray, *, model: str | None = None) -> VlmResult:
    """Read all text in the image. The image should already be cropped to the receipt."""
    s = get_settings()
    model = model or s.vlm_model
    # Never below vlm_max_side: smaller images make glm-ocr change digits.
    image = resize_max_side(image, s.vlm_max_side)
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise ValueError("Could not encode the image for the VLM.")

    client = ollama.Client(host=s.ollama_host, timeout=s.vlm_timeout_s)
    started = time.perf_counter()
    text, cut, chunks = "", False, 0
    try:
        stream = client.chat(
            model=model, stream=True, keep_alive=s.keep_alive,
            messages=[{"role": "user", "content": _PROMPT, "images": [buffer.tobytes()]}],
            options={"temperature": 0, "seed": 42, "num_predict": _MAX_TOKENS},
        )
        for part in stream:
            text += part.message.content or ""
            chunks += 1
            if chunks % 20 == 0 and text.count("\n") > 2 * _REPEAT_WINDOW:
                text, cut = cut_repetition(text)
                if cut:
                    stream.close()  # closing the connection makes Ollama stop generating
                    break
            if time.perf_counter() - started > s.vlm_timeout_s:
                raise LLMError(f"Timed out: '{model}' took longer than {s.vlm_timeout_s:.0f} s.")
    except ollama.ResponseError as error:
        if error.status_code == 404:
            raise LLMError(f"Model '{model}' is not installed. Run: ollama pull {model}") from error
        raise LLMError(f"Ollama error: {error}") from error
    except httpx.TimeoutException as error:
        raise LLMError(f"Timed out: '{model}' did not answer within {s.vlm_timeout_s:.0f} s.") from error
    except (httpx.ConnectError, ConnectionError) as error:
        raise LLMError(f"Cannot reach Ollama at {s.ollama_host}. Is it running?") from error

    if not cut:
        text, cut = cut_repetition(text)
    h, w = image.shape[:2]
    return VlmResult(text=text.strip(), seconds=round(time.perf_counter() - started, 2),
                     engine=f"ollama/{model}", image_size=(int(w), int(h)), repetition_cut=cut)
