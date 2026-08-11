import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from src.config import get_settings
from src.database import database_connection


class FaceEnrollmentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class KnownFace:
    person_id: str
    name: str
    embedding: np.ndarray


class FaceGallery:
    """Thread-safe, database-backed cache; no SQLite reads occur per frame."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._faces: tuple[KnownFace, ...] = ()

    def reload(self) -> int:
        faces: list[KnownFace] = []
        with database_connection() as connection:
            rows = connection.execute(
                """SELECT fp.person_id, p.display_name, fp.embedding, fp.embedding_dimension
                   FROM face_profiles fp JOIN persons p ON p.id = fp.person_id
                   WHERE fp.is_active = 1 AND p.is_active = 1
                   ORDER BY p.display_name, fp.created_at"""
            ).fetchall()
        for row in rows:
            embedding = np.frombuffer(row["embedding"], dtype=np.float32)
            if embedding.size != row["embedding_dimension"] or not np.isfinite(embedding).all():
                continue
            faces.append(KnownFace(row["person_id"], row["display_name"], embedding.copy()))
        with self._lock:
            self._faces = tuple(faces)
            return len(self._faces)

    def snapshot(self) -> tuple[KnownFace, ...]:
        with self._lock:
            return self._faces


class FaceIdentityService:
    def __init__(self, gallery: FaceGallery, insightface_root: Path, provider: str = "auto") -> None:
        self.gallery = gallery
        self.insightface_root = insightface_root.expanduser().resolve()
        self.provider = provider.strip().lower()
        self._lock = threading.RLock()
        self._face_app: Any = None

    def extract(self, image_bytes: bytes) -> tuple[np.ndarray, float]:
        if not image_bytes or len(image_bytes) > 10 * 1024 * 1024:
            raise FaceEnrollmentError("Face image must be between 1 byte and 10 MB")
        try:
            import cv2
        except ImportError as exc:
            raise FaceEnrollmentError(f"OpenCV is unavailable: {exc}") from exc
        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.ndim != 3:
            raise FaceEnrollmentError("Face image is invalid or unsupported")
        faces = self._app().get(image)
        if not faces:
            raise FaceEnrollmentError("No face was detected in the supplied image")
        face = max(faces, key=lambda item: (item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1]))
        embedding = np.asarray(face.embedding, dtype=np.float32).reshape(-1)
        if embedding.size == 0 or not np.isfinite(embedding).all():
            raise FaceEnrollmentError("InsightFace returned an invalid embedding")
        return embedding, float(getattr(face, "det_score", 0.0))

    def _app(self):
        with self._lock:
            if self._face_app is not None:
                return self._face_app
            model_dir = self.insightface_root / "models" / "buffalo_l"
            required = {"1k3d68.onnx", "2d106det.onnx", "det_10g.onnx", "genderage.onnx", "w600k_r50.onnx"}
            present = {item.name for item in model_dir.glob("*.onnx")} if model_dir.is_dir() else set()
            missing = sorted(required - present)
            if missing:
                raise FaceEnrollmentError(
                    f"Missing local InsightFace buffalo_l resources: {', '.join(missing)}"
                )
            try:
                from insightface import app as insightface_app
            except ImportError as exc:
                raise FaceEnrollmentError(f"InsightFace is unavailable: {exc}") from exc
            providers, ctx_id = self._execution_provider()
            face_app = insightface_app.FaceAnalysis(
                name="buffalo_l",
                providers=providers,
                root=str(self.insightface_root),
            )
            face_app.prepare(ctx_id=ctx_id, det_size=(640, 640))
            self._face_app = face_app
            return face_app

    def _execution_provider(self) -> tuple[list[str], int]:
        if self.provider not in {"auto", "cpu", "directml"}:
            raise FaceEnrollmentError("Identity provider must be auto, cpu, or directml")
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise FaceEnrollmentError(f"ONNX Runtime is unavailable: {exc}") from exc
        available = set(ort.get_available_providers())
        if self.provider in {"auto", "directml"} and "DmlExecutionProvider" in available:
            return ["DmlExecutionProvider", "CPUExecutionProvider"], 0
        if self.provider == "directml":
            raise FaceEnrollmentError("DirectML was requested but is unavailable")
        return ["CPUExecutionProvider"], -1


face_gallery = FaceGallery()
_settings = get_settings()
face_identity_service = FaceIdentityService(
    face_gallery,
    _settings.vision_insightface_root,
    _settings.vision_identity_provider,
)
