from uuid import uuid4

from src.database import BUILTIN_VIDEO_CAMERA_ID, database_connection, initialize_database


def test_metrics_migration_is_idempotent_and_preserves_existing_data():
    with database_connection() as connection:
        password_hash = connection.execute(
            "SELECT password_hash FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone()[0]
        event_id = str(uuid4())
        connection.execute(
            """INSERT INTO events
               (id, camera_id, event_type, occurred_at, ai_model_name, ai_model_version)
               VALUES (?, ?, 'person_detected', '2026-08-01T00:00:00+00:00', 'legacy', '1')""",
            (event_id, BUILTIN_VIDEO_CAMERA_ID),
        )
        connection.execute("DROP TABLE operational_camera_metrics")
        connection.execute("DROP TABLE hub_metrics")
    initialize_database()
    initialize_database()
    with database_connection() as connection:
        assert connection.execute("SELECT count(*) FROM events WHERE id = ?", (event_id,)).fetchone()[0] == 1
        assert connection.execute(
            "SELECT password_hash FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone()[0] == password_hash
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {"hub_metrics", "operational_camera_metrics"} <= tables
