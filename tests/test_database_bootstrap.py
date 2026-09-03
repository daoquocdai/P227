import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from src.config import get_settings
from src.database import (
    BUILTIN_LAPTOP_CAMERA_ID,
    BUILTIN_VIDEO_CAMERA_ID,
    DEFAULT_VIDEO_SOURCE,
    initialize_database,
)
from src.services.camera_service import camera_service


@pytest.fixture
def fresh_database(tmp_path, monkeypatch):
    path = tmp_path / "fresh.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path.as_posix()}")
    get_settings.cache_clear()
    try:
        yield path
    finally:
        get_settings.cache_clear()


def cameras(path: Path):
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            """SELECT c.*, cs.source_kind, cs.source_uri, cs.playback_path
               FROM cameras c LEFT JOIN camera_sources cs ON cs.camera_id = c.id
               ORDER BY c.name"""
        ).fetchall()


def delete_camera(path: Path, camera_id: str):
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
        connection.commit()


def test_fresh_database_has_exactly_two_default_cameras_and_restart_is_idempotent(fresh_database):
    initialize_database()
    first = cameras(fresh_database)
    initialize_database()
    second = cameras(fresh_database)

    assert len(first) == len(second) == 2
    assert [row["name"] for row in second] == ["Laptop Camera", "Video Camera"]
    laptop = next(row for row in second if row["id"] == BUILTIN_LAPTOP_CAMERA_ID)
    video = next(row for row in second if row["id"] == BUILTIN_VIDEO_CAMERA_ID)
    assert (laptop["source_kind"], laptop["source_uri"]) == ("webcam", "0")
    assert (video["source_kind"], video["source_uri"], video["playback_path"]) == (
        "video_file",
        DEFAULT_VIDEO_SOURCE,
        DEFAULT_VIDEO_SOURCE,
    )

    with sqlite3.connect(fresh_database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'emergency_%'"
            )
        }
        assert tables == {"emergency_contacts", "emergency_escalation_attempts"}
        assert "help_requested_at" in {row[1] for row in connection.execute("PRAGMA table_info(incidents)")}


@pytest.mark.parametrize("missing_id", [BUILTIN_LAPTOP_CAMERA_ID, BUILTIN_VIDEO_CAMERA_ID])
def test_startup_adds_only_the_missing_default(fresh_database, missing_id):
    initialize_database()
    delete_camera(fresh_database, missing_id)
    initialize_database()

    rows = cameras(fresh_database)
    assert len(rows) == 2
    assert {row["id"] for row in rows} == {BUILTIN_LAPTOP_CAMERA_ID, BUILTIN_VIDEO_CAMERA_ID}


def test_existing_both_are_not_duplicated_or_reset(fresh_database):
    initialize_database()
    with sqlite3.connect(fresh_database) as connection:
        connection.execute(
            "UPDATE cameras SET is_active = 1, vision_enabled = 0 WHERE id = ?",
            (BUILTIN_LAPTOP_CAMERA_ID,),
        )
        connection.commit()
    initialize_database()

    rows = cameras(fresh_database)
    laptop = next(row for row in rows if row["id"] == BUILTIN_LAPTOP_CAMERA_ID)
    assert len(rows) == 2
    assert (laptop["is_active"], laptop["vision_enabled"]) == (1, 0)


def test_changed_video_source_survives_restart(fresh_database):
    initialize_database()
    selected = "videos/kich_ban5.mp4"
    with sqlite3.connect(fresh_database) as connection:
        connection.execute(
            "UPDATE cameras SET source_reference = ? WHERE id = ?",
            (selected, BUILTIN_VIDEO_CAMERA_ID),
        )
        connection.execute(
            "UPDATE camera_sources SET source_uri = ?, playback_path = ? WHERE camera_id = ?",
            (selected, selected, BUILTIN_VIDEO_CAMERA_ID),
        )
        connection.commit()
    initialize_database()

    video = next(row for row in cameras(fresh_database) if row["id"] == BUILTIN_VIDEO_CAMERA_ID)
    assert (video["source_reference"], video["source_uri"], video["playback_path"]) == (
        selected,
        selected,
        selected,
    )


def test_custom_camera_is_preserved(fresh_database):
    initialize_database()
    custom_id = str(uuid4())
    with sqlite3.connect(fresh_database) as connection:
        connection.execute(
            """INSERT INTO cameras
               (id, name, source_type, source_reference, location_label, is_active)
               VALUES (?, 'Custom Camera', 'webcam', '2', 'Garage', 0)""",
            (custom_id,),
        )
        connection.execute(
            """INSERT INTO camera_sources (camera_id, source_kind, source_uri)
               VALUES (?, 'webcam', '2')""",
            (custom_id,),
        )
        connection.commit()
    initialize_database()

    rows = cameras(fresh_database)
    assert len(rows) == 3
    assert any(row["id"] == custom_id and row["source_uri"] == "2" for row in rows)


def test_existing_default_name_with_another_id_is_accepted(fresh_database):
    initialize_database()
    delete_camera(fresh_database, BUILTIN_LAPTOP_CAMERA_ID)
    replacement_id = str(uuid4())
    with sqlite3.connect(fresh_database) as connection:
        connection.execute(
            """INSERT INTO cameras
               (id, name, source_type, source_reference, location_label, is_active)
               VALUES (?, 'Laptop Camera', 'webcam', '3', 'Desk', 0)""",
            (replacement_id,),
        )
        connection.execute(
            """INSERT INTO camera_sources (camera_id, source_kind, source_uri)
               VALUES (?, 'webcam', '3')""",
            (replacement_id,),
        )
        connection.commit()
    initialize_database()

    rows = cameras(fresh_database)
    assert len(rows) == 2
    replacement = next(row for row in rows if row["name"] == "Laptop Camera")
    assert (replacement["id"], replacement["source_uri"]) == (replacement_id, "3")


def test_legacy_identity_config_is_ignored_by_product_contract(fresh_database):
    initialize_database()
    with sqlite3.connect(fresh_database) as connection:
        connection.execute(
            "UPDATE camera_sources SET config_json = ? WHERE camera_id = ?",
            ('{"loop_video":false,"identity_enabled":false}', BUILTIN_VIDEO_CAMERA_ID),
        )
        connection.commit()

    initialize_database()
    desired = next(item for item in camera_service.desired_states() if item["id"] == BUILTIN_VIDEO_CAMERA_ID)
    camera = camera_service.get_camera(BUILTIN_VIDEO_CAMERA_ID)

    assert desired["loop_video"] is False
    assert "identity_enabled" not in desired
    assert "identity_enabled" not in camera
