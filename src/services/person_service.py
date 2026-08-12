from typing import Any
from uuid import uuid4

from src.database import database_connection
from src.services.face_identity_service import FaceIdentityService, face_identity_service


class PersonNotFoundError(Exception):
    pass


class FaceProfileNotFoundError(Exception):
    pass


class PersonService:
    def __init__(self, identity: FaceIdentityService | None = None) -> None:
        self._identity = identity or face_identity_service

    def list_people(self) -> list[dict[str, Any]]:
        with database_connection() as connection:
            people = connection.execute("SELECT * FROM persons ORDER BY display_name").fetchall()
            return [self._person(connection, person) for person in people]

    def get_person(self, person_id: str) -> dict[str, Any]:
        with database_connection() as connection:
            person = connection.execute("SELECT * FROM persons WHERE id = ?", (person_id,)).fetchone()
            if not person:
                raise PersonNotFoundError(person_id)
            return self._person(connection, person)

    def create_person(self, data) -> dict[str, Any]:
        person_id = str(uuid4())
        with database_connection() as connection:
            connection.execute(
                """INSERT INTO persons
                   (id, display_name, relationship_label, date_of_birth, notes, is_active)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    person_id,
                    data.name.strip(),
                    data.relationship,
                    data.birth.isoformat() if data.birth else None,
                    data.notes,
                    int(data.active),
                ),
            )
        return self.get_person(person_id)

    def update_person(self, person_id: str, data) -> dict[str, Any]:
        fields = data.model_dump(exclude_unset=True)
        if fields.get("name") is None:
            fields.pop("name", None)
        mapping = {
            "name": "display_name",
            "relationship": "relationship_label",
            "birth": "date_of_birth",
            "notes": "notes",
            "active": "is_active",
        }
        if not fields:
            return self.get_person(person_id)
        assignments = ", ".join(f"{mapping[key]} = ?" for key in fields)
        values = [
            int(value) if key == "active" else value.isoformat() if key == "birth" and value else value
            for key, value in fields.items()
        ]
        with database_connection() as connection:
            updated = connection.execute(
                f"UPDATE persons SET {assignments}, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                (*values, person_id),
            )
            if updated.rowcount == 0:
                raise PersonNotFoundError(person_id)
        self._identity.gallery.reload()
        return self.get_person(person_id)

    def add_face(self, person_id: str, image_bytes: bytes, angle: str) -> dict[str, Any]:
        person = self.get_person(person_id)
        face_id = str(uuid4())
        embedding, quality = self._identity.extract(image_bytes)
        with database_connection() as connection:
            connection.execute(
                """INSERT INTO face_profiles
                   (id, person_id, model_name, model_version, embedding,
                    embedding_dimension, quality_score, is_active, angle_label)
                   VALUES (?, ?, 'buffalo_l', 'insightface-v1', ?, ?, ?, 1, ?)""",
                (face_id, person_id, embedding.tobytes(), embedding.size, quality, angle),
            )
            
        import os
        import time
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
        register_dir = os.path.join(base_dir, "register face", person["name"])
        os.makedirs(register_dir, exist_ok=True)
        timestamp = int(time.time())
        file_path = os.path.join(register_dir, f"static_{timestamp}_{face_id[:8]}.jpg")
        with open(file_path, "wb") as f:
            f.write(image_bytes)
            
        self._identity.gallery.reload()
        return self.get_person(person_id)

    def add_face_video(self, person_id: str, images_bytes: list[bytes]) -> dict[str, Any]:
        person = self.get_person(person_id)
        person_name = person["name"]
        
        successful_faces = 0
        for i, image_bytes in enumerate(images_bytes):
            try:
                face_id = str(uuid4())
                embedding, quality = self._identity.extract(image_bytes)
                with database_connection() as connection:
                    connection.execute(
                        """INSERT INTO face_profiles
                           (id, person_id, model_name, model_version, embedding,
                            embedding_dimension, quality_score, is_active, angle_label)
                           VALUES (?, ?, 'buffalo_l', 'insightface-v1', ?, ?, ?, 1, ?)""",
                        (face_id, person_id, embedding.tobytes(), embedding.size, quality, f"Frame {i+1}"),
                    )
                successful_faces += 1
            except Exception as e:
                print(f"Bỏ qua frame {i+1} do lỗi trích xuất: {e}")
                
        if successful_faces == 0:
            from src.services.face_identity_service import FaceEnrollmentError
            raise FaceEnrollmentError("Không tìm thấy khuôn mặt rõ ràng trong video.")
            
        import os
        import time
        # Path to `register face` folder which is one level up from `P-227-visionv2_be_fe`
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
        register_dir = os.path.join(base_dir, "register face", person_name)
        os.makedirs(register_dir, exist_ok=True)
        
        timestamp = int(time.time())
        for i, image_bytes in enumerate(images_bytes):
            file_path = os.path.join(register_dir, f"frame_{timestamp}_{i:04d}.jpg")
            with open(file_path, "wb") as f:
                f.write(image_bytes)
                
        self._identity.gallery.reload()
        return self.get_person(person_id)

    def delete_face(self, person_id: str, face_id: str) -> dict[str, Any]:
        with database_connection() as connection:
            deleted = connection.execute(
                "DELETE FROM face_profiles WHERE id = ? AND person_id = ?", (face_id, person_id)
            )
            if deleted.rowcount == 0:
                raise FaceProfileNotFoundError(face_id)
        self._identity.gallery.reload()
        return self.get_person(person_id)

    @staticmethod
    def _person(connection, person) -> dict[str, Any]:
        faces = connection.execute(
            """SELECT id, model_name, model_version, quality_score, is_active, angle_label
               FROM face_profiles WHERE person_id = ? ORDER BY created_at""",
            (person["id"],),
        ).fetchall()
        return {
            "id": person["id"],
            "name": person["display_name"],
            "relationship": person["relationship_label"] or "Người thân",
            "birth": person["date_of_birth"],
            "notes": person["notes"],
            "active": bool(person["is_active"]),
            "faces": [
                {
                    "id": face["id"],
                    "quality": face["quality_score"] or 0,
                    "angle": face["angle_label"] or "Ảnh khuôn mặt",
                    "model": f"{face['model_name']} {face['model_version']}",
                    "active": bool(face["is_active"]),
                }
                for face in faces
            ],
        }


person_service = PersonService()
