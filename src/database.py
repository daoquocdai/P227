import hashlib
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from src.config import get_settings

BUILTIN_LAPTOP_CAMERA_ID = "8d691d84-8c3e-4b8f-96ee-2ef832c49e51"
BUILTIN_VIDEO_CAMERA_ID = "73da9967-26fc-4ed0-b049-bbd901453c8a"
DEFAULT_VIDEO_SOURCE = "videos/kich_ban3.mp4"


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
        ensure_builtin_cameras(connection)
        connection.commit()
    return path


def ensure_builtin_cameras(connection: sqlite3.Connection) -> None:
    """Create missing built-in cameras without resetting existing records."""
    defaults = (
        (
            BUILTIN_LAPTOP_CAMERA_ID,
            "Laptop Camera",
            "webcam",
            "0",
            "Laptop",
            "webcam",
            "0",
            None,
        ),
        (
            BUILTIN_VIDEO_CAMERA_ID,
            "Video Camera",
            "video_file",
            DEFAULT_VIDEO_SOURCE,
            "Video",
            "video_file",
            DEFAULT_VIDEO_SOURCE,
            DEFAULT_VIDEO_SOURCE,
        ),
    )
    for camera_id, name, source_type, source_reference, location, source_kind, source_uri, playback_path in defaults:
        existing = connection.execute(
            "SELECT id FROM cameras WHERE id = ? OR name = ? LIMIT 1",
            (camera_id, name),
        ).fetchone()
        if existing is not None:
            continue
        connection.execute(
            """INSERT INTO cameras
               (id, name, source_type, source_reference, location_label,
                operational_status, is_active, vision_enabled)
               VALUES (?, ?, ?, ?, ?, 'offline', 0, 1)""",
            (camera_id, name, source_type, source_reference, location),
        )
        connection.execute(
            """INSERT INTO camera_sources
               (camera_id, source_kind, source_uri, playback_path)
               VALUES (?, ?, ?, ?)""",
            (camera_id, source_kind, source_uri, playback_path),
        )


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
        CREATE INDEX IF NOT EXISTS idx_events_occurred ON events(occurred_at DESC);
        CREATE TABLE IF NOT EXISTS frame_metrics (
            camera_id TEXT NOT NULL REFERENCES cameras(id) ON UPDATE CASCADE ON DELETE RESTRICT,
            frame_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            fps REAL,
            latency_ms REAL,
            dropped INTEGER NOT NULL DEFAULT 0 CHECK (dropped IN (0, 1)),
            source_type TEXT,
            PRIMARY KEY (camera_id, frame_id)
        );
        CREATE TABLE IF NOT EXISTS hub_metrics (
            id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
            measured_at TEXT NOT NULL,
            process_cpu_percent REAL CHECK (process_cpu_percent BETWEEN 0.0 AND 100.0),
            process_rss_mb REAL CHECK (process_rss_mb >= 0.0),
            host_memory_total_mb REAL CHECK (host_memory_total_mb >= 0.0),
            host_memory_used_percent REAL CHECK (host_memory_used_percent BETWEEN 0.0 AND 100.0),
            disk_used_percent REAL CHECK (disk_used_percent BETWEEN 0.0 AND 100.0)
        );
        CREATE INDEX IF NOT EXISTS idx_hub_metrics_measured
            ON hub_metrics(measured_at DESC);
        CREATE TABLE IF NOT EXISTS operational_camera_metrics (
            id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
            camera_id TEXT NOT NULL REFERENCES cameras(id) ON UPDATE CASCADE ON DELETE CASCADE,
            measured_at TEXT NOT NULL,
            camera_status TEXT NOT NULL CHECK (camera_status IN ('connecting', 'online', 'offline', 'error')),
            last_seen_at TEXT,
            raw_fps REAL CHECK (raw_fps >= 0.0),
            vision_status TEXT NOT NULL CHECK (vision_status IN ('disabled', 'error', 'running', 'waiting_for_source')),
            vision_fps REAL CHECK (vision_fps >= 0.0),
            vision_processing_latency_ms REAL CHECK (vision_processing_latency_ms >= 0.0),
            vision_drop_ratio REAL CHECK (vision_drop_ratio BETWEEN 0.0 AND 1.0),
            pending INTEGER CHECK (pending >= 0),
            max_pending INTEGER CHECK (max_pending >= 0),
            vision_frames_offered INTEGER CHECK (vision_frames_offered >= 0),
            vision_frames_overwritten INTEGER CHECK (vision_frames_overwritten >= 0)
        );
        CREATE INDEX IF NOT EXISTS idx_operational_camera_metrics_camera_measured
            ON operational_camera_metrics(camera_id, measured_at DESC);
        CREATE INDEX IF NOT EXISTS idx_operational_camera_metrics_measured
            ON operational_camera_metrics(measured_at DESC);
        CREATE TABLE IF NOT EXISTS system_settings (
            setting_key TEXT PRIMARY KEY NOT NULL,
            value_json TEXT NOT NULL CHECK (json_valid(value_json)),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );
        CREATE TABLE IF NOT EXISTS agent_runs (
            id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
            event_id TEXT NOT NULL REFERENCES events(id) ON UPDATE CASCADE ON DELETE CASCADE,
            alert_id TEXT NOT NULL REFERENCES alerts(id) ON UPDATE CASCADE ON DELETE CASCADE,
            model TEXT NOT NULL,
            policy_version TEXT NOT NULL DEFAULT 'gate2-v1',
            status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'skipped')),
            attempt INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
            verdict TEXT CHECK (verdict IS NULL OR verdict IN ('CONFIRMED_ALERT', 'UNCERTAIN', 'DUPLICATE')),
            severity TEXT CHECK (severity IS NULL OR severity IN ('low', 'medium', 'high', 'critical')),
            reason_summary TEXT CHECK (reason_summary IS NULL OR length(reason_summary) <= 500),
            error_code TEXT CHECK (error_code IS NULL OR length(error_code) <= 100),
            started_at TEXT, completed_at TEXT,
            latency_ms REAL CHECK (latency_ms IS NULL OR latency_ms >= 0),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            UNIQUE (event_id, policy_version)
        );
        CREATE INDEX IF NOT EXISTS idx_agent_runs_event ON agent_runs(event_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS agent_actions (
            id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
            run_id TEXT NOT NULL REFERENCES agent_runs(id) ON UPDATE CASCADE ON DELETE CASCADE,
            event_id TEXT NOT NULL REFERENCES events(id) ON UPDATE CASCADE ON DELETE CASCADE,
            tool_name TEXT NOT NULL CHECK (tool_name IN ('get_incident_context', 'get_event_context', 'enrich_incident_alert')),
            action_type TEXT NOT NULL CHECK (action_type IN ('read', 'enrichment')),
            status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'reused')),
            safe_arguments_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(safe_arguments_json)),
            safe_result_summary TEXT CHECK (safe_result_summary IS NULL OR length(safe_result_summary) <= 1000),
            duration_ms REAL CHECK (duration_ms IS NULL OR duration_ms >= 0),
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_agent_actions_run ON agent_actions(run_id, created_at, id);
        CREATE TABLE IF NOT EXISTS incidents (
            id TEXT PRIMARY KEY NOT NULL, camera_id TEXT NOT NULL REFERENCES cameras(id),
            incident_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', opened_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL, occurrence_count INTEGER NOT NULL DEFAULT 1, track_id TEXT,
            source_session TEXT, episode_key TEXT, version INTEGER NOT NULL DEFAULT 1,
            review_requested_version INTEGER NOT NULL DEFAULT 0, summary_version INTEGER NOT NULL DEFAULT 0,
            agent_summary TEXT, acknowledged_at TEXT, acknowledged_by TEXT REFERENCES users(id),
            help_requested_at TEXT,
            resolved_at TEXT, resolved_by TEXT REFERENCES users(id), resolution_reason TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_incidents_correlation ON incidents(camera_id, incident_type, status, track_id, source_session, last_seen_at DESC);
        CREATE TABLE IF NOT EXISTS incident_events (
            incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
            event_id TEXT NOT NULL UNIQUE REFERENCES events(id) ON DELETE CASCADE,
            disposition TEXT NOT NULL DEFAULT 'attached',
            attached_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            PRIMARY KEY (incident_id, event_id)
        );
        CREATE TABLE IF NOT EXISTS incident_actions (
            id TEXT PRIMARY KEY NOT NULL, incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
            action_type TEXT NOT NULL, event_id TEXT REFERENCES events(id), user_id TEXT REFERENCES users(id),
            incident_version INTEGER NOT NULL, note TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_incident_actions_incident ON incident_actions(incident_id, created_at, id);
        CREATE TABLE IF NOT EXISTS emergency_contacts (
            id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
            display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
            relationship_label TEXT,
            phone_e164 TEXT NOT NULL CHECK (
                substr(phone_e164, 1, 1) = '+' AND substr(phone_e164, 2, 1) BETWEEN '1' AND '9' AND
                substr(phone_e164, 2) NOT GLOB '*[^0-9]*' AND length(phone_e164) BETWEEN 9 AND 16
            ),
            priority INTEGER NOT NULL DEFAULT 1 CHECK (priority >= 1),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_emergency_contacts_active_priority
            ON emergency_contacts(is_active, priority, created_at, id);
        CREATE TABLE IF NOT EXISTS emergency_escalation_attempts (
            id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
            incident_id TEXT NOT NULL REFERENCES incidents(id) ON UPDATE CASCADE ON DELETE CASCADE,
            contact_id TEXT REFERENCES emergency_contacts(id) ON UPDATE CASCADE ON DELETE RESTRICT,
            channel TEXT NOT NULL DEFAULT 'call' CHECK (channel = 'call'),
            stage TEXT NOT NULL DEFAULT 'fall_unconfirmed' CHECK (stage = 'fall_unconfirmed'),
            status TEXT NOT NULL CHECK (status IN ('pending', 'claimed', 'succeeded', 'failed', 'cancelled')),
            attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
            incident_version INTEGER NOT NULL CHECK (incident_version >= 1),
            idempotency_key TEXT NOT NULL UNIQUE,
            provider_reference TEXT,
            error_code TEXT CHECK (error_code IS NULL OR length(error_code) <= 100),
            retryable INTEGER NOT NULL DEFAULT 0 CHECK (retryable IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            UNIQUE (incident_id, stage, contact_id, attempt_number)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_emergency_escalation_success
            ON emergency_escalation_attempts(incident_id, stage) WHERE status = 'succeeded';
        CREATE INDEX IF NOT EXISTS idx_emergency_escalation_incident
            ON emergency_escalation_attempts(incident_id, stage, created_at, id);
        """
    )
    alert_columns = {row[1] for row in connection.execute("PRAGMA table_info(alerts)").fetchall()}
    if "is_read" not in alert_columns:
        connection.execute("ALTER TABLE alerts ADD COLUMN is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1))")
    if "incident_id" not in alert_columns:
        connection.execute("ALTER TABLE alerts ADD COLUMN incident_id TEXT REFERENCES incidents(id)")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_alerts_incident ON alerts(incident_id) WHERE incident_id IS NOT NULL"
        )
    run_columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_runs)").fetchall()}
    if "incident_id" not in run_columns:
        connection.execute("ALTER TABLE agent_runs ADD COLUMN incident_id TEXT REFERENCES incidents(id)")
    if "incident_version" not in run_columns:
        connection.execute("ALTER TABLE agent_runs ADD COLUMN incident_version INTEGER")
    if "review_generation" not in run_columns:
        connection.execute("ALTER TABLE agent_runs ADD COLUMN review_generation INTEGER NOT NULL DEFAULT 1")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_runs_incident_generation ON agent_runs(incident_id, review_generation) WHERE incident_id IS NOT NULL"
    )
    incident_columns = {row[1] for row in connection.execute("PRAGMA table_info(incidents)").fetchall()}
    if "help_requested_at" not in incident_columns:
        connection.execute("ALTER TABLE incidents ADD COLUMN help_requested_at TEXT")
    action_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_actions'"
    ).fetchone()[0]
    if "get_incident_context" not in action_sql:
        connection.executescript(
            """
            ALTER TABLE agent_actions RENAME TO agent_actions_legacy;
            CREATE TABLE agent_actions (
                id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                tool_name TEXT NOT NULL CHECK (tool_name IN ('get_incident_context','get_event_context','enrich_incident_alert')),
                action_type TEXT NOT NULL CHECK (action_type IN ('read','enrichment')),
                status TEXT NOT NULL CHECK (status IN ('succeeded','failed','reused')),
                safe_arguments_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(safe_arguments_json)),
                safe_result_summary TEXT, duration_ms REAL, idempotency_key TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            INSERT INTO agent_actions SELECT id,run_id,event_id,
                CASE tool_name WHEN 'get_recent_alerts' THEN 'get_incident_context' WHEN 'enrich_alert' THEN 'enrich_incident_alert' ELSE tool_name END,
                action_type,status,safe_arguments_json,safe_result_summary,duration_ms,idempotency_key,created_at
                FROM agent_actions_legacy;
            DROP TABLE agent_actions_legacy;
            CREATE INDEX idx_agent_actions_run ON agent_actions(run_id,created_at,id);
            """
        )
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
    missing_admins = connection.execute(
        "SELECT id FROM users WHERE role = 'admin' AND password_hash IS NULL"
    ).fetchall()
    if missing_admins:
        initial_password = os.getenv("ANTAM_INITIAL_ADMIN_PASSWORD", "AnTam@123")
        for admin in missing_admins:
            salt = os.urandom(16)
            iterations = 210_000
            digest = hashlib.pbkdf2_hmac("sha256", initial_password.encode(), salt, iterations)
            encoded = f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"
            connection.execute(
                """UPDATE users SET password_hash = ?, force_password_change = 1
                   WHERE id = ?""",
                (encoded, admin[0]),
            )
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
def database_connection(*, initialize: bool = True) -> Iterator[sqlite3.Connection]:
    # Most existing call sites retain the idempotent bootstrap behavior. The
    # periodic collector opts out after application startup so migrations and
    # password bootstrap are not repeated on every sample.
    path = initialize_database() if initialize else sqlite_path()
    if not path.is_file():
        raise RuntimeError("Database is not initialized; call initialize_database() during startup")
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
