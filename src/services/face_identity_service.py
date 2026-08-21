from __future__ import annotations

from pathlib import Path

import numpy as np

from sda_vision import FaceEncoder, FaceEncoderConfig, FaceEncodingError

from src.config import get_settings
from src.services.face_embedding_encoder import FaceEnrollmentError


class FaceGallery:
    """Compatibility adapter used only by the explicit legacy rollback path."""

    def __init__(self):
        self._entries = ()

    def reload(self):
        from src.services.face_gallery_provider import SqliteFaceGalleryProvider
        self._entries = SqliteFaceGalleryProvider().load("legacy")[0].entries
        return len(self._entries)

    def snapshot(self):
        return self._entries


class FaceIdentityService:
    """Thin application adapter; model/provider ownership stays in SDA."""

    def __init__(self, insightface_root: Path, provider: str = "auto") -> None:
        device = {"directml": "amd"}.get(provider.strip().lower(), provider.strip().lower())
        self._encoder = FaceEncoder(FaceEncoderConfig(
            insightface_root=insightface_root, device=device))

    def extract(self, image_bytes: bytes) -> tuple[np.ndarray, float]:
        try:
            result = self._encoder.encode(image_bytes)
        except FaceEncodingError as exc:
            raise FaceEnrollmentError(str(exc)) from exc
        return result.embedding, result.quality


_settings = get_settings()
face_gallery = FaceGallery()
face_identity_service = FaceIdentityService(
    _settings.vision_insightface_root,
    _settings.vision_identity_provider,
)
