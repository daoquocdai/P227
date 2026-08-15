import hashlib
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from src.config import get_settings


def sqlite_path() -> Path:
    url = get_settings().database_url
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError("Baseline only supports DATABASE_URL=sqlite:///...")
    path = Path(url.removeprefix(prefix))
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def initialize_database() -> Path:
    path = sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    schema_path = Path(__file__).resolve().parents[1] / "database" / "schema.sql"

    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'events'").fetchone()
        if not exists:
            connection.executescript(schema_path.read_text(encoding="utf-8"))
        _apply_runtime_migrations(connection)
        connection.commit()
    return path


def _apply_runtime_migrations(connection: sqlite3.Connection) -> None:
    """Small idempotent migrations for databases created before runtime integration."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS camera_sources (
            camera_id TEXT PRIMARY KEY NOT NULL REFERENCES cameras(id) ON UPDATE CASCADE ON DELETE CASCADE,
            source_kind TEXT NOT NULL CHECK (source_kind IN ('video_file', 'webcam', 'rtsp')),
            source_uri TEXT,
            playback_path TEXT,
            config_json TEXT,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            CHECK (source_kind = 'webcam' OR length(trim(source_uri)) > 0)
        );
        CREATE INDEX IF NOT EXISTS idx_camera_sources_kind ON camera_sources(source_kind);
        CREATE TABLE IF NOT EXISTS device_metrics (
            id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
            camera_id TEXT REFERENCES cameras(id) ON UPDATE CASCADE ON DELETE CASCADE,
            measured_at TEXT NOT NULL,
            ram_usage_mb REAL CHECK (ram_usage_mb >= 0),
            ram_total_mb REAL CHECK (ram_total_mb >= 0),
            cpu_usage_percent REAL CHECK (cpu_usage_percent BETWEEN 0.0 AND 100.0),
            ping_ms REAL CHECK (ping_ms >= 0),
            disk_usage_percent REAL CHECK (disk_usage_percent BETWEEN 0.0 AND 100.0),
            CHECK (
                ram_usage_mb IS NOT NULL OR cpu_usage_percent IS NOT NULL OR
                ping_ms IS NOT NULL OR disk_usage_percent IS NOT NULL
            )
        );
        CREATE INDEX IF NOT EXISTS idx_device_metrics_camera_measured
            ON device_metrics(camera_id, measured_at DESC);
        CREATE TABLE IF NOT EXISTS system_settings (
            setting_key TEXT PRIMARY KEY NOT NULL,
            value_json TEXT NOT NULL CHECK (json_valid(value_json)),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );
        """
    )
    alert_columns = {row[1] for row in connection.execute("PRAGMA table_info(alerts)").fetchall()}
    if "is_read" not in alert_columns:
        connection.execute("ALTER TABLE alerts ADD COLUMN is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1))")
    face_columns = {row[1] for row in connection.execute("PRAGMA table_info(face_profiles)").fetchall()}
    if "angle_label" not in face_columns:
        connection.execute("ALTER TABLE face_profiles ADD COLUMN angle_label TEXT")
    camera_columns = {row[1] for row in connection.execute("PRAGMA table_info(cameras)").fetchall()}
    if "vision_enabled" not in camera_columns:
        connection.execute(
            "ALTER TABLE cameras ADD COLUMN vision_enabled INTEGER NOT NULL DEFAULT 1 CHECK (vision_enabled IN (0, 1))"
        )
    user_columns = {row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
    if "password_hash" not in user_columns:
        connection.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    if "force_password_change" not in user_columns:
        connection.execute("ALTER TABLE users ADD COLUMN force_password_change INTEGER NOT NULL DEFAULT 0")
    connection.execute(
        """INSERT OR IGNORE INTO system_settings (setting_key, value_json) VALUES
           ('general', '{"retention_days":30,"stranger_threshold":78,"fall_threshold":72,"sensitive_enabled":true,"sensitive_from":"22:00","sensitive_to":"06:00"}'),
           ('notifications', '{"app":true,"email":true,"sms":false,"level":"all","grouped":true,"quiet_enabled":true,"quiet_from":"22:00","quiet_to":"06:00"}')"""
    )
    connection.execute(
        """INSERT OR IGNORE INTO users (id, email, display_name, role, is_active)
           VALUES ('11111111-1111-4111-8111-111111111111', 'admin@example.local', 'Quản trị viên', 'admin', 1)"""
    )
    admin_password = os.getenv("ANTAM_INITIAL_ADMIN_PASSWORD", "AnTam@123")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", admin_password.encode(), salt, 210_000)
    encoded = f"pbkdf2_sha256$210000${salt.hex()}${digest.hex()}"
    connection.execute("UPDATE users SET password_hash=? WHERE role='admin' AND password_hash IS NULL", (encoded,))
    demo_videos = ("videos/45353-448489443_medium.mp4", "videos/76621-559757958.mp4")
    cameras = connection.execute(
        "SELECT id, source_type, source_reference FROM cameras ORDER BY created_at, id"
    ).fetchall()
    for index, camera in enumerate(cameras):
        exists = connection.execute("SELECT 1 FROM camera_sources WHERE camera_id = ?", (camera[0],)).fetchone()
        if exists:
            continue
        source_kind = "webcam" if camera[1] == "webcam" and camera[2].isdigit() else "video_file"
        playback_path = None if source_kind == "webcam" else demo_videos[index % len(demo_videos)]
        source_uri = camera[2] if source_kind == "webcam" else playback_path
        connection.execute(
            "INSERT INTO camera_sources (camera_id, source_kind, source_uri, playback_path) VALUES (?, ?, ?, ?)",
            (camera[0], source_kind, source_uri, playback_path),
        )


@contextmanager
def database_connection() -> Iterator[sqlite3.Connection]:
    path = initialize_database()
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
