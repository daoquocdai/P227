"""Small public API for reusable SDA-GCN Vision sessions."""
from .callbacks import VisionCallbacks
from .config import VisionSessionConfig
from .face_encoder import (FaceEncoder, FaceEncoderConfig, FaceEncodingError,
                           FaceEncodingResult)
from .contracts import (BBoxCoordinateSpace, IdentityGalleryEntry,
                        IdentityGallerySnapshot, VisionDetection, VisionEvent,
                        VisionFrameResult, VisionSourceFrame)

__all__ = [
    "BBoxCoordinateSpace", "FaceEncoder", "FaceEncoderConfig", "FaceEncodingError",
    "FaceEncodingResult", "IdentityGalleryEntry", "IdentityGallerySnapshot",
    "VisionCallbacks", "VisionDetection", "VisionEvent",
    "VisionFrameResult", "VisionSession", "VisionSessionConfig", "VisionSourceFrame",
]


def __getattr__(name):
    if name == "VisionSession":
        from .session import VisionSession
        return VisionSession
    raise AttributeError(name)
