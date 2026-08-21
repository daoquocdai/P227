"""Lazy SDA-native InsightFace enrollment encoder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading

import numpy as np

from .runtime.hardware import probe_capabilities, resolve_face_providers


class FaceEncodingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FaceEncoderConfig:
    insightface_root: Path = Path.home() / ".insightface"
    device: str = "auto"
    detector_size: int = 640


@dataclass(frozen=True, slots=True)
class FaceEncodingResult:
    embedding: np.ndarray
    quality: float


class FaceEncoder:
    def __init__(self, config: FaceEncoderConfig | None = None):
        self.config = config or FaceEncoderConfig()
        self._lock = threading.RLock()
        self._face_app = None
        self.provider_diagnostics = None

    def encode(self, image_bytes: bytes) -> FaceEncodingResult:
        if not image_bytes or len(image_bytes) > 10 * 1024 * 1024:
            raise FaceEncodingError("Face image must be between 1 byte and 10 MB")
        import cv2
        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.ndim != 3:
            raise FaceEncodingError("Face image is invalid or unsupported")
        with self._lock:
            try:
                faces = self._app().get(image)
            except Exception as exc:
                raise FaceEncodingError(f"InsightFace inference failed: {exc}") from exc
        if not faces:
            raise FaceEncodingError("No face was detected in the supplied image")
        if len(faces) != 1:
            raise FaceEncodingError("Enrollment image must contain exactly one face")
        face = faces[0]
        embedding = np.asarray(face.embedding, dtype=np.float32).reshape(-1).copy()
        if embedding.size == 0 or not np.isfinite(embedding).all():
            raise FaceEncodingError("InsightFace returned an invalid embedding")
        return FaceEncodingResult(embedding, float(getattr(face, "det_score", 0.0)))

    def _app(self):
        if self._face_app is not None:
            return self._face_app
        root = self.config.insightface_root.expanduser().resolve()
        model_dir = root / "models" / "buffalo_l"
        required = {"det_10g.onnx", "w600k_r50.onnx"}
        present = {item.name for item in model_dir.glob("*.onnx")} if model_dir.is_dir() else set()
        missing = sorted(required - present)
        if missing:
            raise FaceEncodingError(
                f"Missing local InsightFace buffalo_l resources: {', '.join(missing)}")
        try:
            import onnxruntime as ort
            from insightface.app import FaceAnalysis
        except ImportError as exc:
            raise FaceEncodingError(f"InsightFace runtime is unavailable: {exc}") from exc
        face_spec = resolve_face_providers(
            self.config.device, probe_capabilities(), ort.get_available_providers())
        providers = list(face_spec.providers)
        app = FaceAnalysis(
            name="buffalo_l", root=str(root),
            allowed_modules=["detection", "recognition"], providers=providers)
        primary = providers[0][0] if isinstance(providers[0], tuple) else providers[0]
        app.prepare(ctx_id=-1 if primary == "CPUExecutionProvider" else 0,
                    det_size=(self.config.detector_size, self.config.detector_size))
        effective = []
        for model in getattr(app, "models", {}).values():
            session = getattr(model, "session", None)
            if session is not None and hasattr(session, "get_providers"):
                effective.extend(session.get_providers())
        self.provider_diagnostics = {
            "backend": face_spec.backend,
            "requested_providers": list(face_spec.providers),
            "effective_providers": list(dict.fromkeys(effective)),
        }
        self._face_app = app
        return app
