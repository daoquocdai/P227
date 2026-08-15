from uuid import uuid4

import numpy as np

from src.database import database_connection
from src.services.face_identity_service import FaceGallery, FaceIdentityService


def test_face_gallery_loads_active_profiles_and_invalidates_deactivated_person():
    person_id = str(uuid4())
    profile_id = str(uuid4())
    embedding = np.linspace(-0.5, 0.5, 512, dtype=np.float32)
    with database_connection() as connection:
        connection.execute(
            "INSERT INTO persons (id, display_name, is_active) VALUES (?, ?, 1)",
            (person_id, "Gallery test person"),
        )
        connection.execute(
            """INSERT INTO face_profiles
               (id, person_id, model_name, model_version, embedding, embedding_dimension, quality_score)
               VALUES (?, ?, 'buffalo_l', 'insightface-v1', ?, ?, 0.95)""",
            (profile_id, person_id, embedding.tobytes(), embedding.size),
        )
        connection.commit()

    gallery = FaceGallery()
    gallery.reload()
    known = next(face for face in gallery.snapshot() if face.person_id == person_id)
    np.testing.assert_array_equal(known.embedding, embedding)

    with database_connection() as connection:
        connection.execute("UPDATE persons SET is_active = 0 WHERE id = ?", (person_id,))
        connection.commit()
    gallery.reload()
    assert all(face.person_id != person_id for face in gallery.snapshot())


def test_face_enrollment_auto_provider_prefers_cuda(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.vision.runtime.VisionRuntimeResolver.available_ort_providers",
        lambda: ("DmlExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"),
    )
    service = FaceIdentityService(FaceGallery(), tmp_path, provider="auto")

    providers, context_id = service._execution_provider()

    assert providers == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert context_id == 0
