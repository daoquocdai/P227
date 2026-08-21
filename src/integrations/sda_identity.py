"""The only application ↔ SDA Identity conversion boundary."""

from pathlib import Path

from sda_vision import (
    FaceEncoder, FaceEncoderConfig, FaceEncodingError,
    IdentityGalleryEntry, IdentityGallerySnapshot,
)

from src.services.face_embedding_encoder import FaceEnrollmentError
from src.services.face_gallery_provider import AppFaceGallerySnapshot
from src.config import get_settings


def to_sda_gallery(snapshot: AppFaceGallerySnapshot) -> IdentityGallerySnapshot:
    return IdentityGallerySnapshot(
        snapshot.revision,
        tuple(IdentityGalleryEntry(entry.person_id, entry.name, entry.embedding)
              for entry in snapshot.entries),
    )


class SdaFaceEmbeddingEncoder:
    def __init__(self, insightface_root: Path, provider: str = "auto"):
        device = {"directml": "amd"}.get(provider.strip().lower(), provider.strip().lower())
        self._encoder = FaceEncoder(FaceEncoderConfig(
            insightface_root=insightface_root, device=device))

    def extract(self, image_bytes: bytes):
        try:
            result = self._encoder.encode(image_bytes)
        except FaceEncodingError as exc:
            raise FaceEnrollmentError(str(exc)) from exc
        return result.embedding, result.quality


class SdaGalleryPublisher:
    def __init__(self, registry):
        self.registry = registry

    def __call__(self, snapshot: AppFaceGallerySnapshot):
        return self.registry.update_identity_gallery(to_sda_gallery(snapshot))


_settings = get_settings()
sda_face_embedding_encoder = SdaFaceEmbeddingEncoder(
    _settings.vision_insightface_root, _settings.vision_identity_provider)
