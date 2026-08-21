"""Non-blocking callback boundary between core Vision and adapters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .contracts import VisionEvent, VisionFrameResult, VisionSourceFrame


@dataclass(slots=True)
class VisionCallbacks:
    on_source_frame: Callable[[VisionSourceFrame], None] | None = None
    on_result: Callable[[VisionFrameResult], None] | None = None
    on_result_frame: Callable[[object, VisionFrameResult], None] | None = None
    on_event: Callable[[VisionEvent], None] | None = None
    on_preview: Callable[[object, VisionFrameResult], None] | None = None
