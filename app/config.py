"""Application settings.

Every value can be overridden with an environment variable prefixed ``BILLS_``
(for example ``BILLS_EXTRACT_MODEL=qwen3:4b``) or in a ``.env`` file in the
project root. See ``.env.example``.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BILLS_",
        env_file=PROJECT_ROOT / ".env",
        extra="ignore",
    )

    # Paths
    data_dir: Path = PROJECT_ROOT / "data"
    db_path: Path = PROJECT_ROOT / "data" / "bills.db"
    uploads_dir: Path = PROJECT_ROOT / "data" / "uploads"
    samples_dir: Path = PROJECT_ROOT / "samples"
    ground_truth_dir: Path = PROJECT_ROOT / "eval" / "ground_truth"
    eval_results_dir: Path = PROJECT_ROOT / "eval" / "results"

    # Ollama
    ollama_host: str = "http://localhost:11434"
    extract_model: str = "qwen3:4b"
    vlm_model: str = "glm-ocr"
    keep_alive: str = "30m"
    num_ctx: int = 4096
    num_thread: int | None = None  # None = let Ollama decide
    extract_timeout_s: float = 180.0
    vlm_timeout_s: float = 240.0
    llm_retries: int = 1

    # RapidOCR
    rapid_ocr_version: str = "PP-OCRv6"  # PP-OCRv4 | PP-OCRv5 | PP-OCRv6
    rapid_model_type: str = "small"  # v6: tiny | small | medium; v4/v5: mobile | server
    rapid_engine: str = "onnxruntime"  # onnxruntime | openvino
    rapid_threads: int = -1  # -1 = all cores
    rapid_det_limit_side_len: int = 736  # detector input size (see rapid_det_limit_type)
    rapid_det_limit_type: str = "min"  # min: shorter side >= limit; max: longer side <= limit
    rapid_box_thresh: float = 0.3  # RapidOCR default 0.5; 0.3 cut CER 10.4% -> 6.6% on the samples
    rapid_unclip_ratio: float = 1.6  # how far boxes are expanded around text

    # Preprocessing
    crop_receipt: bool = True  # find + crop the receipt (used for the VLM and the UI)
    # RapidOCR finds text itself; on the samples the full photo scored slightly better
    # than the crop (CER 10.4% vs 11.4%) and was faster, so it gets the full photo.
    rapid_use_crop: bool = False
    # Shadow removal: CER 6.6% -> 5.7% on the samples but worse on receipt_1; re-check with more receipts.
    rapid_remove_shadows: bool = False
    rapid_max_side: int = 1600
    vlm_max_side: int = 896  # below ~800 px glm-ocr starts changing digits
    min_receipt_area: float = 0.15  # fraction of photo; smaller -> use full image

    # Pipeline decisions
    ocr_confidence_threshold: float = 0.85
    vlm_mode: str = "auto"  # auto | always | never
    sum_tolerance_abs: float = 0.05
    sum_tolerance_rel: float = 0.01

    # Chat
    chat_model: str | None = None  # None = extract_model
    chat_timeout_s: float = 90.0
    chat_history_turns: int = 3  # earlier questions sent along for follow-ups ("and in July?")
    chat_rephrase: bool = False  # second LLM call to reword the template answer (~10-20 s more)

    # Server. lan_key is set by `python -m app.cli serve --lan`; without it only this computer may connect.
    port: int = 8000
    lan_key: str | None = None

    # Uploads
    max_upload_mb: int = 15


@lru_cache
def get_settings() -> Settings:
    return Settings()
