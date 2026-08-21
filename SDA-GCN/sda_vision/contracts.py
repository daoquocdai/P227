"""Stable public data contracts emitted by a Vision session."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import numpy as np


class BBoxCoordinateSpace(str, Enum):
    SOURCE_PIXELS = "source_pixels"


@dataclass(frozen=True, slots=True)
class IdentityGalleryEntry:
    person_id: str
    name: str
    embedding: np.ndarray

    def __post_init__(self):
        person_id = self.person_id.strip()
        name = self.name.strip()
        embedding = np.asarray(self.embedding, dtype=np.float32).reshape(-1).copy()
        if not person_id or not name:
            raise ValueError("Identity gallery person_id and name must be non-empty")
        if embedding.size == 0 or not np.isfinite(embedding).all():
            raise ValueError("Identity gallery embedding must be non-empty and finite")
        object.__setattr__(self, "person_id", person_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "embedding", embedding)


@dataclass(frozen=True, slots=True)
class IdentityGallerySnapshot:
    version: int | str
    entries: tuple[IdentityGalleryEntry, ...] = ()

    def __post_init__(self):
        entries = tuple(self.entries)
        dimensions = {entry.embedding.size for entry in entries}
        if len(dimensions) > 1:
            raise ValueError("Identity gallery embeddings must use one dimension")
        object.__setattr__(self, "entries", entries)


@dataclass(frozen=True, slots=True)
class VisionDetection:
    label: str
    confidence: float | None = None
    bbox: tuple[int, int, int, int] | None = None
    bbox_coordinate_space: BBoxCoordinateSpace = BBoxCoordinateSpace.SOURCE_PIXELS
    identity_state: str | None = None
    identity_status: str | None = None
    identity_name: str | None = None
    identity_person_id: str | None = None
    identity_confidence: float | None = None
    face_bbox: tuple[int, int, int, int] | None = None
    association_id: str | int | None = None


@dataclass(frozen=True, slots=True)
class VisionEvent:
    event_type: str
    confidence: float
    frame_sequence: int
    source_time_s: float
    identity_state: str | None = None
    identity_name: str | None = None
    identity_person_id: str | None = None
    person_bbox: tuple[int, int, int, int] | None = None
    face_bbox: tuple[int, int, int, int] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VisionFrameResult:
    camera_id: str
    frame_sequence: int
    source_frame_index: int | None
    source_epoch: int
    source_time_s: float
    captured_wall_time: datetime | None
    current_action: str
    fall_state: str
    fall_confidence: float | None
    detections: tuple[VisionDetection, ...] = ()
    generated_events: tuple[VisionEvent, ...] = ()
    stage_metrics: dict[str, float | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VisionSourceFrame:
    camera_id: str
    frame_sequence: int
    source_frame_index: int | None
    source_epoch: int
    source_time_s: float
    captured_wall_time: datetime | None
    frame: object


@dataclass(frozen=True, slots=True)
class FrameTransform:
    source_width: int
    source_height: int
    inference_width: int = 1280
    inference_height: int = 720

    @property
    def scale(self) -> float:
        return min(self.inference_width / self.source_width,
                   self.inference_height / self.source_height)

    @property
    def padding(self) -> tuple[int, int]:
        resized_width = int(self.source_width * self.scale)
        resized_height = int(self.source_height * self.scale)
        return ((self.inference_width - resized_width) // 2,
                (self.inference_height - resized_height) // 2)

    def bbox_to_source(self, bbox: tuple[int, int, int, int] | None):
        if bbox is None:
            return None
        pad_x, pad_y = self.padding
        x1, y1, x2, y2 = bbox
        mapped = (
            round((x1 - pad_x) / self.scale), round((y1 - pad_y) / self.scale),
            round((x2 - pad_x) / self.scale), round((y2 - pad_y) / self.scale),
        )
        return (max(0, min(self.source_width, mapped[0])),
                max(0, min(self.source_height, mapped[1])),
                max(0, min(self.source_width, mapped[2])),
                max(0, min(self.source_height, mapped[3])))
