from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class VisionDetection:
    label: str
    confidence: float

    bbox_xyxy: tuple[int, int, int, int] | None = None
    track_id: int | None = None

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VisionEvent:
    type: str
    confidence: float

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VisionResult:
    camera_id: str
    frame_id: int

    captured_at: float
    processed_at: float
    processing_ms: float

    detections: list[VisionDetection] = field(default_factory=list)
    events: list[VisionEvent] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)
