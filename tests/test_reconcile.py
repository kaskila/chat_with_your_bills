from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from app.config import get_settings
from app.llm.client import LLMError
from app.pipeline import run
from app.pipeline.extract import Extraction, LlmItem
from app.pipeline.reconcile import reconcile
from app.pipeline.validate import validate
from tests.test_validate import receipt

TODAY = date(2026, 10, 9)
TEXT_14 = ("Rice 5kg 176.00\n2 x Mealie meal 10kg 296.00\nSUBTOTAL 472.00\nVAT 16% 75.52\nTOTAL 547.52")


def good():
    items = [LlmItem(description="Rice 5kg", quantity=None, unit_price=None, amount=176, category="Grocery"),
             LlmItem(description="Mealie meal 10kg", quantity=2, unit_price=None, amount=296, category="Grocery")]
    return receipt(items=items, subtotal=472, tax=75.52, total=547.52, amount_paid=None, change=None)


def bad():
    # shifted amounts: items mismatched and no total found
    items = [LlmItem(description="Rice 5kg", quantity=None, unit_price=None, amount=296, category="Grocery")]
    return receipt(items=items, subtotal=472, tax=75.52, total=None, amount_paid=None, change=None)


def test_second_reading_wins_when_it_has_fewer_number_problems():
    first, second = validate(bad(), ocr_text=TEXT_14, today=TODAY), validate(good(), ocr_text=TEXT_14, today=TODAY)
    choice = reconcile(first, second)
    assert choice.source == "vlm" and choice.chosen is second
    assert "Second reading (VLM) used" in choice.notes[0]
    assert not choice.extra_warnings


def test_first_reading_kept_when_already_consistent():
    first, second = validate(good(), ocr_text=TEXT_14, today=TODAY), validate(bad(), ocr_text=TEXT_14, today=TODAY)
    choice = reconcile(first, second)
    assert choice.source == "rapid" and not choice.extra_warnings
    assert "first reading kept" in choice.notes[0]


def test_disagreeing_totals_flagged_when_neither_reading_is_consistent():
    a = validate(receipt(total=50, subtotal=60, amount_paid=None, change=None), today=TODAY)
    b = validate(receipt(total=70, subtotal=60, amount_paid=None, change=None), today=TODAY)
    choice = reconcile(a, b)
    assert choice.source == "rapid"
    assert [w.code for w in choice.extra_warnings] == ["OCR_DISAGREEMENT"]


# --- process_image decision flow (OCR, VLM and model replaced by fakes) ---

@pytest.fixture
def fakes(monkeypatch):
    calls = {"vlm": 0, "extract": []}
    prep = SimpleNamespace(for_ocr=np.zeros((10, 10, 3), np.uint8), for_vlm=np.zeros((10, 10, 3), np.uint8),
                           seconds=0.01, crop_method="none", receipt_fraction=1.0,
                           quality=SimpleNamespace(warnings=[]))
    monkeypatch.setattr(run, "preprocess", lambda source: prep)
    monkeypatch.setattr(run, "run_ocr", lambda image: SimpleNamespace(
        text="RAPID TEXT " + TEXT_14, mean_confidence=0.97, engine="rapid", seconds=1.0))

    def fake_vlm(image):
        calls["vlm"] += 1
        return SimpleNamespace(text="VLM TEXT " + TEXT_14, engine="ollama/glm-ocr", seconds=50.0)

    monkeypatch.setattr(run, "run_vlm", fake_vlm)
    calls["answers"] = {"RAPID": bad(), "VLM": good()}

    def fake_extract(text):
        key = text.split()[0]
        calls["extract"].append(key)
        return Extraction(receipt=calls["answers"][key], raw=f"{{{key}}}", stats={})

    monkeypatch.setattr(run, "extract", fake_extract)
    yield calls
    get_settings.cache_clear()


def set_mode(monkeypatch, mode):
    monkeypatch.setenv("BILLS_VLM_MODE", mode)
    get_settings.cache_clear()


def test_auto_mode_runs_vlm_on_problems_and_uses_better_reading(fakes, monkeypatch):
    set_mode(monkeypatch, "auto")
    stages = []
    result = run.process_image(b"img", on_stage=stages.append)
    assert fakes["vlm"] == 1 and result.source == "vlm"
    assert result.receipt.total == 547.52 and result.status == "verified"
    assert result.ocr_text_vlm.startswith("VLM TEXT") and result.extraction_raw == "{VLM}"
    assert stages == ["preprocess", "ocr", "extract", "validate", "vlm", "vlm_extract"]
    assert {"vlm_s", "extract2_s", "total_s"} <= result.timings.keys()


def test_auto_mode_skips_vlm_when_first_reading_is_clean(fakes, monkeypatch):
    set_mode(monkeypatch, "auto")
    fakes["answers"]["RAPID"] = good()
    result = run.process_image(b"img")
    assert fakes["vlm"] == 0 and result.source == "rapid" and result.ocr_text_vlm is None


def test_never_mode_and_force(fakes, monkeypatch):
    set_mode(monkeypatch, "never")
    assert run.process_image(b"img").source == "rapid" and fakes["vlm"] == 0
    assert run.process_image(b"img", force_vlm=True).source == "vlm" and fakes["vlm"] == 1


def test_vlm_failure_keeps_first_reading(fakes, monkeypatch):
    set_mode(monkeypatch, "auto")

    def broken(image):
        raise LLMError("Timed out: 'glm-ocr' did not answer within 240 s.")

    monkeypatch.setattr(run, "run_vlm", broken)
    result = run.process_image(b"img")
    assert result.source == "rapid" and result.status == "needs_review"
    assert any("Second reading (VLM) failed" in n for n in result.notes)


def test_vlm_repetition_is_cut():
    from app.pipeline.ocr_vlm import cut_repetition

    once = "SUNRISE BAKERY\n08/10/2026\n-----\n2 x Meat pie 36.00\nScones 6pk 30.00\nTOTAL 88.00\nThank you!"
    looped = once + "\n---\n-----\n2 x Meat pie 36.00\nScones 6pk 30.00\nTOTAL 88.00\nThank you!\n-----\n2 x Meat"
    text, cut = cut_repetition(looped)
    assert cut and text.endswith("Thank you!") and text.count("Meat pie") == 1
    assert cut_repetition(once) == (once, False)
    # the same item three times in a row is not a repetition
    same = "SHOP\nSoda 10.00\nSoda 10.00\nSoda 10.00\nSoda 10.00\nTOTAL 40.00"
    assert cut_repetition(same) == (same, False)
