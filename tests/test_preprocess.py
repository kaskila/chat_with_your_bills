import cv2
import numpy as np
import pytest

from app.pipeline.preprocess import assess_quality, crop_receipt, load_image, preprocess, resize_max_side


def synthetic_photo(angle: float = 0.0, with_white_object: bool = False) -> np.ndarray:
    """Brown 'table' with a white 'receipt' (with dark text lines), optionally rotated."""
    photo = np.full((1000, 800, 3), (40, 70, 110), np.uint8)  # BGR brown
    receipt = np.full((700, 300, 3), 235, np.uint8)
    for y in range(40, 680, 40):
        cv2.putText(receipt, "ITEM 12.50", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (30, 30, 30), 2)
    canvas = np.zeros_like(photo)
    canvas[150:850, 250:550] = receipt
    mask = np.zeros(photo.shape[:2], np.uint8)
    mask[150:850, 250:550] = 255
    if angle:
        m = cv2.getRotationMatrix2D((400, 500), angle, 1.0)
        canvas = cv2.warpAffine(canvas, m, (800, 1000))
        mask = cv2.warpAffine(mask, m, (800, 1000))
    photo[mask > 0] = canvas[mask > 0]
    if with_white_object:
        # A laptop corner 30 px from the receipt.
        photo[0:120, 600:800] = 225
    return photo


def test_resize_only_downscales():
    small = np.zeros((100, 50, 3), np.uint8)
    assert resize_max_side(small, 1600).shape == (100, 50, 3)
    assert resize_max_side(np.zeros((2000, 1000, 3), np.uint8), 1000).shape[:2] == (1000, 500)


@pytest.mark.parametrize("angle", [0.0, 8.0, -12.0])
def test_crop_finds_receipt_and_straightens(angle):
    cropped, method, fraction, rotation = crop_receipt(synthetic_photo(angle))
    assert method in ("perspective", "rotated_rect")
    assert 0.2 < fraction < 0.35  # receipt is 700x300 of an 1000x800 photo = 26%
    h, w = cropped.shape[:2]
    assert 690 <= h <= 780 and 290 <= w <= 380  # receipt size plus padding
    assert cropped.mean() > 180  # mostly paper, little table


def test_nearby_white_object_is_not_merged():
    cropped, _, fraction, _ = crop_receipt(synthetic_photo(with_white_object=True))
    assert fraction < 0.35
    assert cropped.shape[1] < 400


def test_no_receipt_keeps_full_image():
    photo = np.full((600, 400, 3), (40, 70, 110), np.uint8)
    cropped, method, fraction, _ = crop_receipt(photo)
    assert method == "none" and fraction == 1.0 and cropped.shape == photo.shape


def test_quality_flags_blur_and_darkness():
    sharp = synthetic_photo()
    assert assess_quality(sharp).warnings == []
    blurred = cv2.GaussianBlur(sharp, (51, 51), 0)
    assert "BLURRY" in assess_quality(blurred).warnings
    assert "TOO_DARK" in assess_quality((sharp * 0.2).astype(np.uint8)).warnings


def test_load_image_from_bytes_and_bad_data():
    ok, buf = cv2.imencode(".jpg", synthetic_photo())
    assert load_image(buf.tobytes()).shape == (1000, 800, 3)
    with pytest.raises(ValueError):
        load_image(b"not an image")


def test_preprocess_outputs_sizes():
    result = preprocess(synthetic_photo(5.0))
    assert max(result.for_vlm.shape[:2]) <= 896
    assert max(result.for_ocr.shape[:2]) <= 1600
    assert result.crop_method != "none"


def test_clean_white_receipt_is_not_overexposed():
    clean = np.full((1000, 800, 3), 246, np.uint8)  # bright paper, nothing clipped
    cv2.putText(clean, "TOTAL 170.00", (50, 500), cv2.FONT_HERSHEY_SIMPLEX, 2, (20, 20, 20), 4)
    assert "OVEREXPOSED" not in assess_quality(clean).warnings
    washed = np.full((1000, 800, 3), 255, np.uint8)
    assert "OVEREXPOSED" in assess_quality(washed).warnings
