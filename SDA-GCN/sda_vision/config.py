"""Public configuration for one reusable Vision session."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .contracts import IdentityGallerySnapshot


@dataclass(slots=True)
class VisionSessionConfig:
    source: str = "0"
    source_mode: Literal["managed", "external"] = "managed"
    source_fps: float | None = None
    camera_id: str = "standalone-camera"
    camera_location: str = "SDA-GCN Standalone"
    source_epoch: int = 0
    loop_video: bool = False
    inference_enabled: bool = True
    stream_reconnect_delay: float = 1.0
    device: str = "auto"
    identity_enabled: bool = True
    vision_fps: float = 15.0
    identity_interval: float = 0.5
    face_det_size: int = 416
    rebuild_face_cache: bool = False
    log_level: str = "info"
    identity_debug: bool = False
    identity_process_priority: str = "normal"
    identity_cpu_affinity: tuple[int, ...] | None = None
    identity_gallery_mode: str = "filesystem"
    identity_gallery_snapshot: IdentityGallerySnapshot | None = None
    preview: str = "none"
    raw_classifier: bool = False
    package_root: Path | None = None
