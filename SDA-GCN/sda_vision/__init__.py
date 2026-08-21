"""Small public API for reusable SDA-GCN Vision sessions."""
from .callbacks import VisionCallbacks
from .config import VisionSessionConfig
from .contracts import (BBoxCoordinateSpace, VisionDetection, VisionEvent,
                        VisionFrameResult, VisionSourceFrame)

__all__ = [
    "BBoxCoordinateSpace", "VisionCallbacks", "VisionDetection", "VisionEvent",
    "VisionFrameResult", "VisionSession", "VisionSessionConfig", "VisionSourceFrame",
]


def __getattr__(name):
    if name == "VisionSession":
        from .session import VisionSession
        return VisionSession
    raise AttributeError(name)
