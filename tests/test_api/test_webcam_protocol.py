from types import SimpleNamespace

from src.api.cameras import webcam_ready_payload


def test_webcam_ready_payload_exposes_runtime_vision_target():
    runtime = SimpleNamespace(
        settings=SimpleNamespace(vision_input_width=960, vision_input_height=540)
    )
    assert webcam_ready_payload(runtime, "publisher-1") == {
        "type": "ready",
        "publisher_id": "publisher-1",
        "vision_input_width": 960,
        "vision_input_height": 540,
    }
