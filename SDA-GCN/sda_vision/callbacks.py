"""Non-blocking callback boundary between core Vision and adapters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .contracts import VisionEvent, VisionFrameResult


@dataclass(slots=True)
class VisionCallbacks:
    on_result: Callable[[VisionFrameResult], None] | None = None
    on_event: Callable[[VisionEvent], None] | None = None
    on_preview: Callable[[object, VisionFrameResult], None] | None = None

