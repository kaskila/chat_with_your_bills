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
