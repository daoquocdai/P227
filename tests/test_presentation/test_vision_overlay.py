from types import SimpleNamespace

import numpy as np
import pytest

from src.presentation.vision_overlay import calculate_text_overlays, render_vision


def result(*, bbox=(20, 100, 700, 1900), state="LOCKED_UNKNOWN", name=None, action="Dung", fall="CLEAR"):
    status = "KNOWN" if name else "UNKNOWN"
    detection = SimpleNamespace(
        bbox_xyxy=bbox,
        metadata={"identity_state": state, "identity_status": status, "identity_name": name},
    )
    return SimpleNamespace(detections=[detection], metadata={"current_action": action, "fall_state": fall})


@pytest.mark.parametrize(
    ("shape", "bbox"),
    [
        ((1920, 1080, 3), (20, 100, 700, 1920)),
        ((1920, 1080, 3), (20, 0, 700, 1200)),
        ((1080, 1920, 3), (100, 50, 1000, 1050)),
        ((1080, 1080, 3), (0, 0, 1080, 1080)),
    ],
)
def test_text_layout_stays_inside_orientation_safe_area(shape, bbox):
    overlays = calculate_text_overlays(shape, result(bbox=bbox))
    safe_margin = round(shape[0] * 0.08)
    assert [overlay.text for overlay in overlays] == ["Unknown", "Action: Dung"]
    for overlay in overlays:
        left, top, right, bottom = overlay.background
        assert 0 <= left < right < shape[1]
        assert safe_margin <= top < bottom <= shape[0] - safe_margin


def test_known_name_and_fall_action_are_preserved():
    overlays = calculate_text_overlays((1920, 1080, 3), result(name="Mai", action="Nga!", fall="CONFIRMED"))
    assert [overlay.text for overlay in overlays] == ["Mai", "Action: Nga!"]
    assert overlays[1].color == (0, 0, 255)


def test_action_without_person_uses_safe_frame_relative_anchor():
    vision_result = SimpleNamespace(detections=[], metadata={"current_action": "Waiting", "fall_state": "CLEAR"})
    overlay = calculate_text_overlays((1920, 1080, 3), vision_result, show_identity=False)[0]
    assert overlay.text == "Action: Waiting"
    assert overlay.background[1] >= round(1920 * 0.08)


def test_show_flags_independently_control_text_and_rectangle(monkeypatch):
    rectangles = []
    monkeypatch.setattr("src.presentation.vision_overlay.cv2.rectangle", lambda *args: rectangles.append(args))
    monkeypatch.setattr("src.presentation.vision_overlay.cv2.putText", lambda *args: None)
    source = np.zeros((1920, 1080, 3), dtype=np.uint8)
    vision_result = result()

    assert [item.text for item in calculate_text_overlays(source.shape, vision_result, show_identity=False)] == [
        "Action: Dung"
    ]
    assert [item.text for item in calculate_text_overlays(source.shape, vision_result, show_fall=False)] == ["Unknown"]
    render_vision(source, vision_result, show_boxes=False, show_identity=True, show_fall=True)
    assert len(rectangles) == 2  # Text backgrounds only; no person bbox rectangle.
