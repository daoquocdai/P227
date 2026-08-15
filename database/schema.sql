PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE users (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    email TEXT NOT NULL CHECK (length(trim(email)) > 3),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    role TEXT NOT NULL CHECK (role IN ('admin', 'caregiver')),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    password_hash TEXT,
    force_password_change INTEGER NOT NULL DEFAULT 0 CHECK (force_password_change IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE UNIQUE INDEX uq_users_email_nocase ON users(lower(email));

CREATE TABLE user_permissions (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    user_id TEXT NOT NULL REFERENCES users(id) ON UPDATE CASCADE ON DELETE CASCADE,
    permission_key TEXT NOT NULL CHECK (permission_key IN (
        'view_history',
        'acknowledge_alert',
        'resolve_alert',
        'manage_cameras',
        'manage_persons',
        'manage_users'
    )),
    is_granted INTEGER NOT NULL DEFAULT 0 CHECK (is_granted IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (user_id, permission_key)
);

CREATE INDEX idx_user_permissions_user ON user_permissions(user_id);

CREATE TABLE system_settings (
    setting_key TEXT PRIMARY KEY NOT NULL,
    value_json TEXT NOT NULL CHECK (json_valid(value_json)),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Admins implicitly have every permission and do not need rows here.
-- UUIDs include hyphens because every id in this schema must be 36 characters.
CREATE TRIGGER trg_default_permissions_on_caregiver_insert
AFTER INSERT ON users
WHEN NEW.role = 'caregiver'
BEGIN
    INSERT INTO user_permissions (id, user_id, permission_key, is_granted)
    VALUES
        (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(6))), NEW.id, 'view_history', 1),
        (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(6))), NEW.id, 'acknowledge_alert', 1),
        (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(6))), NEW.id, 'resolve_alert', 0),
        (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(6))), NEW.id, 'manage_cameras', 0),
        (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(6))), NEW.id, 'manage_persons', 0),
        (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(6))), NEW.id, 'manage_users', 0);
END;

CREATE TABLE persons (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    relationship_label TEXT,
    date_of_birth TEXT CHECK (date_of_birth IS NULL OR date_of_birth GLOB '????-??-??'),
    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE face_profiles (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    person_id TEXT NOT NULL REFERENCES persons(id) ON UPDATE CASCADE ON DELETE CASCADE,
    model_name TEXT NOT NULL CHECK (length(trim(model_name)) > 0),
    model_version TEXT NOT NULL CHECK (length(trim(model_version)) > 0),
    embedding BLOB NOT NULL CHECK (length(embedding) > 0),
    embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension > 0),
    quality_score REAL CHECK (quality_score BETWEEN 0.0 AND 1.0),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    angle_label TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_face_profiles_person_active
    ON face_profiles(person_id, is_active);

CREATE TABLE cameras (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    name TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0),
    source_type TEXT NOT NULL CHECK (source_type IN ('webcam', 'video_file')),
    source_reference TEXT NOT NULL CHECK (length(trim(source_reference)) > 0),
    location_label TEXT NOT NULL CHECK (length(trim(location_label)) > 0),
    operational_status TEXT NOT NULL DEFAULT 'offline'
        CHECK (operational_status IN ('online', 'offline', 'error')),
    last_seen_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    vision_enabled INTEGER NOT NULL DEFAULT 1 CHECK (vision_enabled IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        source_type = 'webcam' OR (
            source_reference NOT LIKE '/%' AND
            source_reference NOT LIKE '\%' AND
            source_reference NOT GLOB '[A-Za-z]:*' AND
            lower(source_reference) NOT LIKE 'file://%' AND
            '/' || replace(source_reference, '\', '/') || '/' NOT LIKE '%/../%'
        )
    )
);

CREATE INDEX idx_cameras_status_last_seen
    ON cameras(operational_status, last_seen_at);

CREATE TABLE camera_sources (
    camera_id TEXT PRIMARY KEY NOT NULL REFERENCES cameras(id) ON UPDATE CASCADE ON DELETE CASCADE,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('video_file', 'webcam', 'rtsp')),
    source_uri TEXT,
    playback_path TEXT,
    config_json TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (source_kind = 'webcam' OR length(trim(source_uri)) > 0),
    CHECK (
        playback_path IS NULL OR (
            playback_path NOT LIKE '/%' AND playback_path NOT LIKE '\%' AND
            playback_path NOT GLOB '[A-Za-z]:*' AND
            '/' || replace(playback_path, '\', '/') || '/' NOT LIKE '%/../%'
        )
    )
);

CREATE INDEX idx_camera_sources_kind ON camera_sources(source_kind);

CREATE TABLE frame_metrics (
    camera_id TEXT NOT NULL REFERENCES cameras(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    frame_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    fps REAL,
    latency_ms REAL,
    dropped INTEGER NOT NULL DEFAULT 0 CHECK (dropped IN (0, 1)),
    source_type TEXT,
    PRIMARY KEY (camera_id, frame_id)
);

CREATE TABLE events (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    camera_id TEXT NOT NULL REFERENCES cameras(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (event_type IN ('person_detected', 'fall_suspected')),
    occurred_at TEXT NOT NULL,
    ended_at TEXT CHECK (ended_at IS NULL OR ended_at >= occurred_at),
    ai_model_name TEXT NOT NULL CHECK (length(trim(ai_model_name)) > 0),
    ai_model_version TEXT NOT NULL CHECK (length(trim(ai_model_version)) > 0),
    ai_confidence REAL CHECK (ai_confidence BETWEEN 0.0 AND 1.0),
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_events_camera_occurred
    ON events(camera_id, occurred_at DESC);
CREATE INDEX idx_events_type_occurred
    ON events(event_type, occurred_at DESC);
CREATE INDEX idx_events_occurred
    ON events(occurred_at DESC);

CREATE TABLE event_persons (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    event_id TEXT NOT NULL REFERENCES events(id) ON UPDATE CASCADE ON DELETE CASCADE,
    person_id TEXT REFERENCES persons(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    track_id TEXT NOT NULL CHECK (length(trim(track_id)) > 0),
    identity_type TEXT NOT NULL CHECK (identity_type IN ('known', 'unknown')),
    ai_confidence REAL CHECK (ai_confidence BETWEEN 0.0 AND 1.0),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL CHECK (last_seen_at >= first_seen_at),
    bounding_box_json TEXT,
    UNIQUE (event_id, track_id),
    CHECK (
        (identity_type = 'known' AND person_id IS NOT NULL) OR
        (identity_type = 'unknown' AND person_id IS NULL)
    )
);

CREATE INDEX idx_event_persons_person_last_seen
    ON event_persons(person_id, last_seen_at DESC)
    WHERE person_id IS NOT NULL;
CREATE INDEX idx_event_persons_identity_first_seen
    ON event_persons(identity_type, first_seen_at);
CREATE INDEX idx_event_persons_event ON event_persons(event_id);

CREATE TABLE fall_event_details (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    event_id TEXT NOT NULL UNIQUE REFERENCES events(id) ON UPDATE CASCADE ON DELETE CASCADE,
    posture TEXT NOT NULL DEFAULT 'unknown'
        CHECK (posture IN ('standing', 'sitting', 'lying', 'transitioning', 'unknown')),
    fall_confidence REAL NOT NULL CHECK (fall_confidence BETWEEN 0.0 AND 1.0),
    immobility_duration_ms INTEGER CHECK (immobility_duration_ms >= 0),
    bounding_box_json TEXT,
    algorithm_details_json TEXT
);

CREATE TABLE media_assets (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    event_id TEXT NOT NULL REFERENCES events(id) ON UPDATE CASCADE ON DELETE CASCADE,
    media_type TEXT NOT NULL DEFAULT 'snapshot' CHECK (media_type = 'snapshot'),
    subject_type TEXT NOT NULL
        CHECK (subject_type IN ('known_person', 'unknown_person', 'fall', 'scene')),
    relative_path TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL CHECK (mime_type IN ('image/jpeg', 'image/png', 'image/webp')),
    is_blurred INTEGER NOT NULL DEFAULT 0 CHECK (is_blurred IN (0, 1)),
    captured_at TEXT NOT NULL,
    retention_until TEXT NOT NULL CHECK (retention_until >= captured_at),
    sha256 TEXT UNIQUE CHECK (sha256 IS NULL OR length(sha256) = 64),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (subject_type <> 'unknown_person' OR is_blurred = 1),
    CHECK (
        length(trim(relative_path)) > 0 AND
        relative_path NOT LIKE '/%' AND
        relative_path NOT LIKE '\%' AND
        relative_path NOT GLOB '[A-Za-z]:*' AND
        lower(relative_path) NOT LIKE 'file://%' AND
        '/' || replace(relative_path, '\', '/') || '/' NOT LIKE '%/../%'
    )
);

CREATE INDEX idx_media_assets_event ON media_assets(event_id);
CREATE INDEX idx_media_assets_retention ON media_assets(retention_until);

CREATE TABLE alerts (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    event_id TEXT NOT NULL REFERENCES events(id) ON UPDATE CASCADE ON DELETE CASCADE,
    alert_type TEXT NOT NULL CHECK (alert_type IN ('unknown_person', 'fall')),
    severity TEXT NOT NULL DEFAULT 'medium'
        CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'acknowledged', 'resolved', 'dismissed')),
    is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
    assigned_user_id TEXT REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    acknowledged_at TEXT,
    resolved_at TEXT,
    UNIQUE (event_id, alert_type),
    CHECK (acknowledged_at IS NULL OR acknowledged_at >= created_at),
    CHECK (resolved_at IS NULL OR resolved_at >= created_at)
);

CREATE INDEX idx_alerts_status_created ON alerts(status, created_at DESC);
CREATE INDEX idx_alerts_open_created ON alerts(created_at DESC) WHERE status = 'open';
CREATE INDEX idx_alerts_type_created ON alerts(alert_type, created_at DESC);

CREATE TABLE alert_actions (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    alert_id TEXT NOT NULL REFERENCES alerts(id) ON UPDATE CASCADE ON DELETE CASCADE,
    user_id TEXT REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    action_type TEXT NOT NULL CHECK (action_type IN (
        'created', 'acknowledged', 'assigned', 'commented',
        'resolved', 'dismissed', 'reopened', 'verdict_recorded'
    )),
    previous_status TEXT CHECK (previous_status IS NULL OR previous_status IN (
        'open', 'acknowledged', 'resolved', 'dismissed'
    )),
    new_status TEXT CHECK (new_status IS NULL OR new_status IN (
        'open', 'acknowledged', 'resolved', 'dismissed'
    )),
    human_verdict TEXT CHECK (human_verdict IS NULL OR human_verdict IN (
        'true_positive', 'false_positive', 'uncertain'
    )),
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        action_type = 'verdict_recorded' OR human_verdict IS NULL
    ),
    CHECK (
        action_type NOT IN ('acknowledged', 'resolved', 'dismissed', 'reopened') OR
        new_status IS NOT NULL
    )
);

CREATE INDEX idx_alert_actions_alert_created
    ON alert_actions(alert_id, created_at, id);
CREATE INDEX idx_alert_actions_verdict_created
    ON alert_actions(human_verdict, created_at)
    WHERE human_verdict IS NOT NULL;

CREATE TABLE evaluation_runs (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    model_name TEXT NOT NULL CHECK (length(trim(model_name)) > 0),
    model_version TEXT NOT NULL CHECK (length(trim(model_version)) > 0),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    started_at TEXT,
    completed_at TEXT CHECK (
        completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at
    ),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE inference_metrics (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    camera_id TEXT NOT NULL REFERENCES cameras(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    evaluation_run_id TEXT REFERENCES evaluation_runs(id) ON UPDATE CASCADE ON DELETE SET NULL,
    measured_at TEXT NOT NULL,
    window_started_at TEXT,
    window_ended_at TEXT,
    fps REAL CHECK (fps >= 0.0),
    latency_ms REAL CHECK (latency_ms >= 0.0),
    precision_score REAL CHECK (precision_score BETWEEN 0.0 AND 1.0),
    recall_score REAL CHECK (recall_score BETWEEN 0.0 AND 1.0),
    false_positive_rate REAL CHECK (false_positive_rate BETWEEN 0.0 AND 1.0),
    sample_count INTEGER CHECK (sample_count >= 0),
    CHECK (
        window_ended_at IS NULL OR window_started_at IS NULL OR
        window_ended_at >= window_started_at
    ),
    CHECK (
        fps IS NOT NULL OR latency_ms IS NOT NULL OR precision_score IS NOT NULL OR
        recall_score IS NOT NULL OR false_positive_rate IS NOT NULL
    )
);

CREATE INDEX idx_metrics_camera_measured
    ON inference_metrics(camera_id, measured_at DESC);
CREATE INDEX idx_metrics_evaluation_run
    ON inference_metrics(evaluation_run_id)
    WHERE evaluation_run_id IS NOT NULL;

-- Periodic observations from the running Local Hub. These tables are kept
-- separate from inference_metrics, whose rows describe offline evaluation.
CREATE TABLE hub_metrics (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(id) = 36),
    measured_at TEXT NOT NULL,
    process_cpu_percent REAL CHECK (process_cpu_percent BETWEEN 0.0 AND 100.0),
    process_rss_mb REAL CHECK (process_rss_mb >= 0.0),
    host_memory_total_mb REAL CHECK (host_memory_total_mb >= 0.0),
    host_memory_used_percent REAL CHECK (host_memory_used_percent BETWEEN 0.0 AND 100.0),
    disk_used_percent REAL CHECK (disk_used_percent BETWEEN 0.0 AND 100.0)
);

CREATE INDEX idx_hub_metrics_measured
    ON hub_metrics(measured_at DESC);

CREATE TABLE operational_camera_metrics (
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

CREATE INDEX idx_operational_camera_metrics_camera_measured
    ON operational_camera_metrics(camera_id, measured_at DESC);
CREATE INDEX idx_operational_camera_metrics_measured
    ON operational_camera_metrics(measured_at DESC);

-- Enforce subtype integrity that cannot be expressed by a CHECK constraint.
CREATE TRIGGER trg_fall_details_event_type_insert
BEFORE INSERT ON fall_event_details
FOR EACH ROW
WHEN (SELECT event_type FROM events WHERE id = NEW.event_id) <> 'fall_suspected'
BEGIN
    SELECT RAISE(ABORT, 'fall details require a fall_suspected event');
END;

CREATE TRIGGER trg_fall_details_event_type_update
BEFORE UPDATE OF event_id ON fall_event_details
FOR EACH ROW
WHEN (SELECT event_type FROM events WHERE id = NEW.event_id) <> 'fall_suspected'
BEGIN
    SELECT RAISE(ABORT, 'fall details require a fall_suspected event');
END;

CREATE TRIGGER trg_alert_event_type_insert
BEFORE INSERT ON alerts
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN NEW.alert_type = 'fall' AND
             (SELECT event_type FROM events WHERE id = NEW.event_id) <> 'fall_suspected'
        THEN RAISE(ABORT, 'fall alert requires a fall_suspected event')
        WHEN NEW.alert_type = 'unknown_person' AND NOT EXISTS (
            SELECT 1 FROM event_persons
            WHERE event_id = NEW.event_id AND identity_type = 'unknown'
        )
        THEN RAISE(ABORT, 'unknown-person alert requires an unknown person track')
    END;
END;

-- AI output is immutable. Human corrections belong in alert_actions.
CREATE TRIGGER trg_events_ai_immutable
BEFORE UPDATE OF camera_id, event_type, occurred_at, ai_model_name,
                 ai_model_version, ai_confidence, metadata_json
ON events
BEGIN
    SELECT RAISE(ABORT, 'initial AI event output is immutable');
END;

CREATE TRIGGER trg_event_persons_ai_immutable
BEFORE UPDATE ON event_persons
BEGIN
    SELECT RAISE(ABORT, 'initial AI person output is immutable');
END;

CREATE TRIGGER trg_fall_details_ai_immutable
BEFORE UPDATE ON fall_event_details
BEGIN
    SELECT RAISE(ABORT, 'initial AI fall output is immutable');
END;

-- Alert history is append-only.
CREATE TRIGGER trg_alert_actions_no_update
BEFORE UPDATE ON alert_actions
BEGIN
    SELECT RAISE(ABORT, 'alert action history is append-only');
END;

CREATE TRIGGER trg_alert_actions_no_delete
BEFORE DELETE ON alert_actions
BEGIN
    SELECT RAISE(ABORT, 'alert action history is append-only');
END;

COMMIT;
