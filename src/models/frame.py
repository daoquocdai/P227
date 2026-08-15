from dataclasses import dataclass

import numpy as np

from src.models.vision import VisionResult


@dataclass(slots=True)
class FramePacket:
    camera_id: str
    frame_id: int
    captured_at: float
    frame: np.ndarray
    # Source-domain time is independent from local capture/publish wall time.
    # It resets when source_epoch changes and may fall back to a monotonic live
    # observation clock when the source has no reliable media timestamp.
    source_timestamp: float | None = None
    source_time_kind: str = "capture_arrival"
    source_epoch: int = 0
    # Zero-based identity inside the current source epoch. Unlike the Vision
    # consumer call count, this remains stable when pending frames are dropped.
    source_frame_index: int | None = None
    discontinuity: bool = False
    # Set synchronously before publication in the production capture path so
    # stream consumers always render the result belonging to this exact frame.
    vision_result: VisionResult | None = None
