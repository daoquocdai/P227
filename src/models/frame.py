from dataclasses import dataclass

import numpy as np


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
    discontinuity: bool = False
