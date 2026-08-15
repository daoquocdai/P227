import numpy as np

from src.models.vision import VisionDetection, VisionResult
from src.vision.renderer import render_vision


def result():
    return VisionResult(
        "cam",
        1,
        1,
        1,
        1,
        [
            VisionDetection(
                "person",
                0.9,
                (10, 10, 30, 40),
                7,
                {"identity_status": "KNOWN", "identity_name": "An"},
            )
        ],
        metadata={"geometry": {"scale": 1, "pad_x": 0, "pad_y": 0}, "current_action": "Nga!"},
    )


def test_all_overlays_off_keeps_clean_pixels():
    frame = np.zeros((80, 80, 3), dtype=np.uint8)
    rendered = render_vision(frame, result(), show_boxes=False, show_identity=False, show_fall=False)
    assert np.array_equal(rendered, frame)


def test_each_presentation_layer_can_render_without_inference():
    frame = np.zeros((80, 80, 3), dtype=np.uint8)
    for flags in (
        {"show_boxes": True, "show_identity": False, "show_fall": False},
        {"show_boxes": False, "show_identity": True, "show_fall": False},
        {"show_boxes": False, "show_identity": False, "show_fall": True},
    ):
        assert np.any(render_vision(frame, result(), **flags))


def test_known_identity_name_reaches_renderer_and_never_creates_unknown_label(monkeypatch):
    labels = []
    monkeypatch.setattr("src.vision.renderer.cv2.putText", lambda _image, text, *_args: labels.append(text))

    render_vision(
        np.zeros((80, 80, 3), dtype=np.uint8),
        result(),
        show_boxes=False,
        show_identity=True,
        show_fall=False,
    )

    assert labels == ["An"]


def test_missing_or_pending_identity_is_not_fabricated_as_unknown(monkeypatch):
    labels = []
    monkeypatch.setattr("src.vision.renderer.cv2.putText", lambda _image, text, *_args: labels.append(text))
    vision_result = result()
    vision_result.detections[0].metadata = {}
    render_vision(
        np.zeros((80, 80, 3), dtype=np.uint8),
        vision_result,
        show_boxes=False,
        show_identity=True,
        show_fall=False,
    )
    vision_result.detections[0].metadata = {
        "identity_status": "UNKNOWN",
        "identity_state": "PENDING",
    }
    render_vision(
        np.zeros((80, 80, 3), dtype=np.uint8),
        vision_result,
        show_boxes=False,
        show_identity=True,
        show_fall=False,
    )

    assert labels == []


def test_locked_unknown_is_rendered_as_unknown(monkeypatch):
    labels = []
    monkeypatch.setattr("src.vision.renderer.cv2.putText", lambda _image, text, *_args: labels.append(text))
    vision_result = result()
    vision_result.detections[0].metadata = {
        "identity_status": "UNKNOWN",
        "identity_state": "LOCKED_UNKNOWN",
    }

    render_vision(
        np.zeros((80, 80, 3), dtype=np.uint8),
        vision_result,
        show_boxes=False,
        show_identity=True,
        show_fall=False,
    )

    assert labels == ["Unknown"]
