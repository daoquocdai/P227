from uuid import uuid4
from types import SimpleNamespace

import numpy as np

from src.database import database_connection
from src.services.face_gallery_provider import FaceGalleryCoordinator, SqliteFaceGalleryProvider
from src.services.face_identity_service import FaceIdentityService


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

    gallery, _ = SqliteFaceGalleryProvider().load(1)
    known = next(face for face in gallery.entries if face.person_id == person_id)
    np.testing.assert_array_equal(known.embedding, embedding)

    with database_connection() as connection:
        connection.execute("UPDATE persons SET is_active = 0 WHERE id = ?", (person_id,))
        connection.commit()
    gallery, _ = SqliteFaceGalleryProvider().load(2)
    assert all(face.person_id != person_id for face in gallery.entries)


def test_face_enrollment_uses_public_sda_encoder(tmp_path):
    service = FaceIdentityService(tmp_path, provider="auto")
    assert service._encoder.config.device == "auto"


def test_person_service_depends_on_replaceable_embedding_encoder():
    from src.services.face_embedding_encoder import FaceEmbeddingEncoder
    from src.services.person_service import PersonService

    class Encoder:
        def extract(self, image_bytes):
            return np.ones(4, dtype=np.float32), 0.8

    class Coordinator:
        def refresh_after_commit(self):
            return 0

    encoder = Encoder()
    service = PersonService(encoder=encoder, gallery_coordinator=Coordinator())
    assert isinstance(encoder, FaceEmbeddingEncoder)
    assert service._face_encoder is encoder


def test_gallery_coordinator_publishes_monotonic_revisions():
    class Provider:
        def load(self, version):
            from sda_vision import IdentityGallerySnapshot
            return IdentityGallerySnapshot(version), {"load_ms": 0.1}

    class Registry:
        def __init__(self): self.versions = []
        def update_identity_gallery(self, snapshot): self.versions.append(snapshot.version)

    coordinator = FaceGalleryCoordinator(Provider())
    registry = Registry()
    coordinator.bind_registry(registry)
    coordinator.refresh()
    coordinator.refresh()
    assert registry.versions == [1, 2]


def test_sqlite_gallery_skips_invalid_and_preserves_multiple_embeddings():
    person_id = str(uuid4())
    with database_connection() as connection:
        connection.execute(
            "INSERT INTO persons (id, display_name, is_active) VALUES (?, ?, 1)",
            (person_id, "Multiple profiles"))
        for index, raw in enumerate((
                np.ones(4, np.float32).tobytes(),
                np.full(4, 2, np.float32).tobytes(),
                b"invalid")):
            connection.execute(
                """INSERT INTO face_profiles
                   (id, person_id, model_name, model_version, embedding,
                    embedding_dimension, is_active)
                   VALUES (?, ?, 'buffalo_l', 'insightface-v1', ?, 4, 1)""",
                (str(uuid4()), person_id, raw))
    snapshot, metrics = SqliteFaceGalleryProvider().load(1)
    assert len(snapshot.entries) == 2
    assert {entry.person_id for entry in snapshot.entries} == {person_id}
    assert metrics["skipped"] == 1


def test_integrated_gallery_mutations_publish_without_camera_restart():
    from src.services.person_service import PersonService

    class Encoder:
        def extract(self, _image):
            return np.array([1, 0, 0, 0], dtype=np.float32), 0.9

    class Registry:
        def __init__(self): self.snapshots = []
        def update_identity_gallery(self, snapshot): self.snapshots.append(snapshot)

    registry = Registry()
    coordinator = FaceGalleryCoordinator(SqliteFaceGalleryProvider())
    coordinator.bind_registry(registry)
    service = PersonService(Encoder(), coordinator)
    person = service.create_person(SimpleNamespace(
        name="E2E person", relationship=None, birth=None, notes=None, active=True))
    with_face = service.add_face(person["id"], b"deterministic", "front")
    assert registry.snapshots[-1].entries[0].person_id == person["id"]
    assert registry.snapshots[-1].entries[0].name == "E2E person"
    face_id = with_face["faces"][0]["id"]
    service.update_person(person["id"], SimpleNamespace(
        model_dump=lambda **_: {"name": "Renamed person"}))
    assert registry.snapshots[-1].entries[0].name == "Renamed person"
    service.delete_face(person["id"], face_id)
    assert registry.snapshots[-1].entries == ()
    assert [snapshot.version for snapshot in registry.snapshots] == [1, 2, 3]
