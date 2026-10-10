"""Turn OCR text into structured receipt data with the local LLM.

The model is forced to answer in the JSON schema of ``LlmReceipt`` (Ollama
structured outputs), so its reply always parses. Values stay "as printed";
``validate.py`` normalizes and checks them.
"""

import json
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.llm.client import ChatResult, LLMError, chat
from app.llm.prompts import EXTRACTION_SYSTEM, extraction_user_message
from app.schemas import Category


class LlmItem(BaseModel):
    description: str
    quantity: float | None
    unit_price: float | None
    amount: float
    category: Category


class LlmReceipt(BaseModel):
    # Field order is generation order: header first, then items, then totals.
    vendor: str | None
    vendor_tax_id: str | None
    receipt_no: str | None
    date: str | None
    time: str | None
    currency: str | None
    items: list[LlmItem]
    subtotal: float | None
    discount: float | None
    service_charge: float | None
    tax: float | None
    total: float | None
    amount_paid: float | None
    change: float | None
    payment_method: str | None


EXTRACTION_SCHEMA = LlmReceipt.model_json_schema()


@dataclass
class Extraction:
    receipt: LlmReceipt
    raw: str
    stats: dict


def extract(ocr_text: str, *, model: str | None = None) -> Extraction:
    model = model or get_settings().extract_model
    messages = [
        {"role": "system", "content": EXTRACTION_SYSTEM},
        {"role": "user", "content": extraction_user_message(ocr_text)},
    ]
    result: ChatResult = chat(model, messages, format=EXTRACTION_SCHEMA)
    try:
        receipt = LlmReceipt.model_validate(json.loads(result.content))
    except (json.JSONDecodeError, ValidationError) as error:
        raise LLMError(f"The model returned data that does not fit the schema: {error}") from error
    return Extraction(receipt=receipt, raw=result.content, stats=result.stats())
