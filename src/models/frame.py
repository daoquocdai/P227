from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class FramePacket:
    camera_id: str
    frame_id: int
    captured_at: float
    frame: np.ndarray