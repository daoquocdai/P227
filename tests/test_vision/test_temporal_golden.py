import json
from pathlib import Path

import numpy as np

from src.models.frame import FramePacket
from src.services.vision_sample_buffer import VisionSampleBuffer


def test_canonical_source_schedule_is_strict_on_sufficient_capacity():
    """Canonical Vision reports strict fidelity for its two-second source window."""
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "vision" / "temporal-window.json"
    golden = json.loads(fixture_path.read_text(encoding="utf-8"))
    inputs = golden["input"]
    expected = golden["expected"]
    buffer = VisionSampleBuffer(target_sample_rate=15.0, inference_skip_factor=2, capacity=8)
    buffer.enable("cam01")
    model_observation_ids = []

    for frame_id in range(inputs["frame_count"]):
        packet = FramePacket(
            camera_id="cam01",
            frame_id=frame_id,
            captured_at=1_000.0 + frame_id / inputs["source_fps"],
            frame=np.zeros((2, 2, 3), dtype=np.uint8),
            source_timestamp=frame_id / inputs["source_fps"],
        )
        assert buffer.offer(packet)
        selected = buffer.get_nowait("cam01")
        assert selected is packet
        sampled = frame_id % inputs["inference_skip_factor"] == 0
        if sampled:
            model_observation_ids.append(frame_id)
        buffer.note_result(
            packet,
            {
                "sampled": sampled,
                "window_source_time_span": expected["window_source_time_span"]
                if frame_id == inputs["frame_count"] - 1
                else None,
            },
        )

    assert model_observation_ids == expected["model_observation_ids"]
    status = buffer.get_status("cam01")
    for key in ("window_source_time_span", "temporal_drop_count", "overload_count", "temporal_fidelity"):
        assert status[key] == expected[key]
