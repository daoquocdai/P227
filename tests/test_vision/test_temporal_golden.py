import numpy as np

from src.models.frame import FramePacket
from src.services.vision_sample_buffer import VisionSampleBuffer


def test_legacy_clean_v1_source_schedule_is_strict_on_sufficient_capacity():
    """Oracle: legacy-clean-v1; input: 127 frames at 30 FPS; truth: V1 executable schedule."""
    buffer = VisionSampleBuffer(target_sample_rate=15.0, legacy_skip_factor=2, capacity=8)
    buffer.enable("cam01")
    model_observation_ids = []

    for frame_id in range(127):
        packet = FramePacket(
            camera_id="cam01",
            frame_id=frame_id,
            captured_at=1_000.0 + frame_id / 30.0,
            frame=np.zeros((2, 2, 3), dtype=np.uint8),
            source_timestamp=frame_id / 30.0,
        )
        assert buffer.offer(packet)
        selected = buffer.get_nowait("cam01")
        assert selected is packet
        sampled = frame_id % 2 == 0
        if sampled:
            model_observation_ids.append(frame_id)
        buffer.note_result(
            packet,
            {
                "sampled": sampled,
                "window_source_time_span": 4.2 if frame_id == 126 else None,
            },
        )

    assert model_observation_ids == list(range(0, 127, 2))
    assert len(model_observation_ids) == 64
    status = buffer.get_status("cam01")
    assert status["window_source_time_span"] == 4.2
    assert status["temporal_drop_count"] == 0
    assert status["overload_count"] == 0
    assert status["temporal_fidelity"] == "strict"
