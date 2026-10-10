from app.pipeline.ocr_rapid import _Box, _is_sideways, group_lines


def box(text, x0, y0, x1, y1, score=0.99):
    return _Box(text, score, x0, y0, x1, y1, 0.0)


def test_boxes_on_same_line_are_joined_left_to_right():
    lines = group_lines([box("160.00", 300, 102, 380, 122), box("Milk shake", 10, 100, 120, 120)])
    assert [l.text for l in lines] == ["Milk shake  160.00"]


def test_stacked_boxes_become_separate_lines():
    # Same x range, slightly overlapping vertically (tilted receipt): must not merge.
    lines = group_lines([box("Bill Printed Time", 10, 100, 200, 120), box("Payment Type:", 10, 112, 160, 132)])
    assert [l.text for l in lines] == ["Bill Printed Time", "Payment Type:"]


def test_lines_are_in_reading_order():
    boxes = [box("Total", 10, 300, 80, 320), box("Header", 10, 10, 100, 30), box("Item", 10, 150, 60, 170)]
    assert [l.text for l in group_lines(boxes)] == ["Header", "Item", "Total"]


def test_line_confidence_is_weighted_by_length():
    lines = group_lines([box("a", 0, 0, 10, 10, score=0.5), box("bbb", 20, 0, 50, 10, score=1.0)])
    assert lines[0].confidence == round((0.5 * 1 + 1.0 * 3) / 4, 4)
    assert lines[0].box == (0, 0, 50, 10)


def test_sideways_detection():
    tall = [box("abcd", 0, i * 100, 20, i * 100 + 90) for i in range(5)]
    wide = [box("abcd", 0, i * 30, 90, i * 30 + 20) for i in range(5)]
    assert _is_sideways(tall)
    assert not _is_sideways(wide)


def test_sideways_photo_keeps_the_line_order():
    """A page photographed sideways, either way round: the lines must come out top to bottom
    (the wrong quarter turn reads almost as well, but upside down, with the lines reversed)."""
    import cv2
    import numpy as np

    from app.pipeline.ocr_rapid import run_ocr

    page = np.full((300, 900, 3), 255, np.uint8)
    for i, text in enumerate(["FIRST LINE 111", "SECOND LINE 222", "THIRD LINE 333", "FOURTH LINE 444"]):
        cv2.putText(page, text, (30, 60 + i * 65), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3)
    for turn in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):
        lines = [line.text for line in run_ocr(cv2.rotate(page, turn)).lines]
        numbers = [next(ch for ch in line if ch.isdigit()) for line in lines if any(ch.isdigit() for ch in line)]
        assert numbers == ["1", "2", "3", "4"], lines


def test_sideways_turn_is_chosen_with_the_line_classifier_off(monkeypatch):
    """The real case (an Airtel message photographed sideways): with RapidOCR's line classifier on,
    the wrong quarter turn scored as well as the right one (150.0 vs 150.4) but returned the lines
    in reverse order. Here the wrong turn even scores higher with it on; it must still lose."""
    from types import SimpleNamespace

    import cv2
    import numpy as np

    from app.pipeline import ocr_rapid

    page = np.arange(6, dtype=np.uint8).reshape(2, 3, 1).repeat(3, axis=2)  # tiny, but every turn differs
    wrong, right = cv2.rotate(page, cv2.ROTATE_90_CLOCKWISE), cv2.rotate(page, cv2.ROTATE_90_COUNTERCLOCKWISE)

    def reading(texts, score, vertical=False):
        quads = [[[0, i * 40], [30 if vertical else 300, i * 40], [30 if vertical else 300, i * 40 + (300 if vertical else 30)],
                  [0, i * 40 + (300 if vertical else 30)]] for i in range(len(texts))]
        return SimpleNamespace(boxes=quads, txts=texts, scores=[score] * len(texts))

    def fake_ocr(image, use_cls=None):
        if image.shape == page.shape and (image == page).all():
            # unrotated, RapidOCR reads the tall boxes too, even scoring higher, but the lines cannot be ordered
            return reading(["THIRD 333", "SECOND 222", "FIRST 111"], 0.99, vertical=True)
        if (image == wrong).all():  # upside down: fine with the classifier, garbage without
            return reading(["THIRD 333", "SECOND 222", "FIRST 111"], 0.99) if use_cls is not False \
                else reading(["Yesy t36", "Z22", "x"], 0.3)
        return reading(["FIRST 111", "SECOND 222", "THIRD 333"], 0.95)

    monkeypatch.setattr(ocr_rapid, "get_engine", lambda *a: fake_ocr)
    result = ocr_rapid.run_ocr(page)
    assert result.rotation_deg == 90.0
    assert [line.text for line in result.lines] == ["FIRST 111", "SECOND 222", "THIRD 333"]
