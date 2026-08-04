PRAGMA foreign_keys = ON;

BEGIN;

INSERT INTO users (id, email, display_name, role, created_at, updated_at) VALUES
('00000000-0000-4000-8000-000000000001', 'admin@example.local', 'Quản trị viên', 'admin', '2026-08-03T00:00:00.000Z', '2026-08-03T00:00:00.000Z'),
('00000000-0000-4000-8000-000000000002', 'caregiver@example.local', 'Minh Nguyễn', 'caregiver', '2026-08-03T00:00:00.000Z', '2026-08-03T00:00:00.000Z'),
('00000000-0000-4000-8000-000000000003', 'maianh@example.local', 'Mai Anh', 'caregiver', '2026-08-03T00:00:00.000Z', '2026-08-03T00:00:00.000Z'),
('00000000-0000-4000-8000-000000000004', 'thanhha@example.local', 'Thanh Hà', 'caregiver', '2026-08-03T00:00:00.000Z', '2026-08-03T00:00:00.000Z');

UPDATE users SET is_active = 0, updated_at = '2026-08-03T01:00:00.000Z'
WHERE id = '00000000-0000-4000-8000-000000000004';

-- Demonstrate per-caregiver overrides after trigger defaults are created.
UPDATE user_permissions
SET is_granted = 1, updated_at = '2026-08-03T01:05:00.000Z'
WHERE user_id = '00000000-0000-4000-8000-000000000003'
  AND permission_key IN ('resolve_alert', 'manage_persons');

INSERT INTO persons (id, display_name, relationship_label, is_active, created_at, updated_at) VALUES
('10000000-0000-4000-8000-000000000001', 'Nguyễn Văn An', 'Ông', 1, '2026-08-03T00:00:00.000Z', '2026-08-03T00:00:00.000Z');

-- Dummy encrypted bytes only; this is not a real face embedding.
INSERT INTO face_profiles (
    id, person_id, model_name, model_version, embedding,
    embedding_dimension, quality_score, created_at
) VALUES (
    '20000000-0000-4000-8000-000000000001',
    '10000000-0000-4000-8000-000000000001',
    'demo-face-model', '1.0', X'01020304', 512, 0.91,
    '2026-08-03T00:00:00.000Z'
);

INSERT INTO cameras (
    id, name, source_type, source_reference, location_label,
    operational_status, last_seen_at, created_at, updated_at
) VALUES
('30000000-0000-4000-8000-000000000001', 'Webcam phòng khách', 'webcam', '0', 'Phòng khách', 'online', '2026-08-03T07:00:00.000Z', '2026-08-03T00:00:00.000Z', '2026-08-03T07:00:00.000Z'),
('30000000-0000-4000-8000-000000000002', 'Video mô phỏng', 'video_file', 'samples/fall-demo.mp4', 'Phòng ngủ', 'offline', NULL, '2026-08-03T00:00:00.000Z', '2026-08-03T00:00:00.000Z');

INSERT INTO events (
    id, camera_id, event_type, occurred_at, ended_at,
    ai_model_name, ai_model_version, ai_confidence, created_at
) VALUES
('40000000-0000-4000-8000-000000000001', '30000000-0000-4000-8000-000000000001', 'person_detected', '2026-08-03T06:30:00.000Z', '2026-08-03T06:30:08.000Z', 'demo-detector', '1.0', 0.94, '2026-08-03T06:30:08.000Z'),
('40000000-0000-4000-8000-000000000002', '30000000-0000-4000-8000-000000000001', 'person_detected', '2026-08-03T06:45:00.000Z', '2026-08-03T06:45:04.000Z', 'demo-detector', '1.0', 0.82, '2026-08-03T06:45:04.000Z'),
('40000000-0000-4000-8000-000000000003', '30000000-0000-4000-8000-000000000002', 'fall_suspected', '2026-08-03T06:50:00.000Z', '2026-08-03T06:50:12.000Z', 'demo-fall-model', '1.0', 0.88, '2026-08-03T06:50:12.000Z');

INSERT INTO event_persons (
    id, event_id, person_id, track_id, identity_type,
    ai_confidence, first_seen_at, last_seen_at
) VALUES
('50000000-0000-4000-8000-000000000001', '40000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000001', 'track-1', 'known', 0.93, '2026-08-03T06:30:00.000Z', '2026-08-03T06:30:08.000Z'),
('50000000-0000-4000-8000-000000000002', '40000000-0000-4000-8000-000000000002', NULL, 'track-2', 'unknown', 0.82, '2026-08-03T06:45:00.000Z', '2026-08-03T06:45:04.000Z'),
('50000000-0000-4000-8000-000000000003', '40000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000001', 'track-3', 'known', 0.90, '2026-08-03T06:50:00.000Z', '2026-08-03T06:50:12.000Z');

INSERT INTO fall_event_details (
    id, event_id, posture, fall_confidence, immobility_duration_ms
) VALUES (
    '60000000-0000-4000-8000-000000000001',
    '40000000-0000-4000-8000-000000000003',
    'lying', 0.88, 5000
);

INSERT INTO media_assets (
    id, event_id, subject_type, relative_path, mime_type,
    is_blurred, captured_at, retention_until, sha256, created_at
) VALUES
('70000000-0000-4000-8000-000000000001', '40000000-0000-4000-8000-000000000002', 'unknown_person', 'snapshots/2026/08/03/unknown-blurred-001.webp', 'image/webp', 1, '2026-08-03T06:45:01.000Z', '2026-08-10T06:45:01.000Z', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', '2026-08-03T06:45:02.000Z'),
('70000000-0000-4000-8000-000000000002', '40000000-0000-4000-8000-000000000003', 'fall', 'snapshots/2026/08/03/fall-001.webp', 'image/webp', 0, '2026-08-03T06:50:03.000Z', '2026-09-02T06:50:03.000Z', 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', '2026-08-03T06:50:04.000Z');

INSERT INTO alerts (
    id, event_id, alert_type, severity, status, assigned_user_id,
    created_at, updated_at, acknowledged_at
) VALUES
('80000000-0000-4000-8000-000000000001', '40000000-0000-4000-8000-000000000002', 'unknown_person', 'medium', 'open', NULL, '2026-08-03T06:45:02.000Z', '2026-08-03T06:45:02.000Z', NULL),
('80000000-0000-4000-8000-000000000002', '40000000-0000-4000-8000-000000000003', 'fall', 'critical', 'acknowledged', '00000000-0000-4000-8000-000000000002', '2026-08-03T06:50:04.000Z', '2026-08-03T06:51:00.000Z', '2026-08-03T06:51:00.000Z');

INSERT INTO alert_actions (
    id, alert_id, user_id, action_type, previous_status,
    new_status, human_verdict, note, created_at
) VALUES
('90000000-0000-4000-8000-000000000001', '80000000-0000-4000-8000-000000000001', NULL, 'created', NULL, 'open', NULL, NULL, '2026-08-03T06:45:02.000Z'),
('90000000-0000-4000-8000-000000000002', '80000000-0000-4000-8000-000000000002', NULL, 'created', NULL, 'open', NULL, NULL, '2026-08-03T06:50:04.000Z'),
('90000000-0000-4000-8000-000000000003', '80000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000002', 'acknowledged', 'open', 'acknowledged', NULL, 'Đã kiểm tra người thân', '2026-08-03T06:51:00.000Z'),
('90000000-0000-4000-8000-000000000004', '80000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000002', 'verdict_recorded', NULL, NULL, 'true_positive', 'Xác nhận có té ngã', '2026-08-03T06:52:00.000Z');

INSERT INTO evaluation_runs (
    id, name, model_name, model_version, status, started_at, completed_at, created_at
) VALUES (
    'a0000000-0000-4000-8000-000000000001', 'Đánh giá demo',
    'demo-detector', '1.0', 'completed',
    '2026-08-03T05:00:00.000Z', '2026-08-03T05:10:00.000Z',
    '2026-08-03T05:00:00.000Z'
);

INSERT INTO inference_metrics (
    id, camera_id, evaluation_run_id, measured_at,
    window_started_at, window_ended_at, fps, latency_ms,
    precision_score, recall_score, false_positive_rate, sample_count
) VALUES
('b0000000-0000-4000-8000-000000000001', '30000000-0000-4000-8000-000000000001', NULL, '2026-08-03T07:00:00.000Z', '2026-08-03T06:59:00.000Z', '2026-08-03T07:00:00.000Z', 24.7, 41.2, NULL, NULL, NULL, 1482),
('b0000000-0000-4000-8000-000000000002', '30000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000001', '2026-08-03T05:10:00.000Z', '2026-08-03T05:00:00.000Z', '2026-08-03T05:10:00.000Z', 23.9, 43.8, 0.92, 0.89, 0.04, 500);

-- Additional fictional demo data -------------------------------------------

INSERT INTO persons (
    id, display_name, relationship_label, date_of_birth, notes,
    is_active, created_at, updated_at
) VALUES
('10000000-0000-4000-8000-000000000002', 'Trần Thị Bình', 'Bà', '1953-11-08', 'Thường sinh hoạt tại phòng khách', 1, '2026-08-03T00:00:00.000Z', '2026-08-03T00:00:00.000Z'),
('10000000-0000-4000-8000-000000000003', 'Nguyễn Minh Châu', 'Con', '1992-04-16', NULL, 1, '2026-08-03T00:00:00.000Z', '2026-08-03T00:00:00.000Z');

-- Dummy encrypted bytes only; these are not real face embeddings.
INSERT INTO face_profiles (
    id, person_id, model_name, model_version, embedding,
    embedding_dimension, quality_score, created_at
) VALUES
('20000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000002', 'demo-face-model', '1.0', X'11121314', 512, 0.89, '2026-08-03T00:00:00.000Z'),
('20000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000003', 'demo-face-model', '1.0', X'21222324', 512, 0.95, '2026-08-03T00:00:00.000Z');

INSERT INTO cameras (
    id, name, source_type, source_reference, location_label,
    operational_status, last_seen_at, created_at, updated_at
) VALUES
('30000000-0000-4000-8000-000000000003', 'Video hành lang', 'video_file', 'samples/hallway-demo.mp4', 'Hành lang', 'online', '2026-08-03T07:04:30.000Z', '2026-08-03T00:00:00.000Z', '2026-08-03T07:04:30.000Z');

INSERT INTO events (
    id, camera_id, event_type, occurred_at, ended_at,
    ai_model_name, ai_model_version, ai_confidence, created_at
) VALUES
('40000000-0000-4000-8000-000000000004', '30000000-0000-4000-8000-000000000001', 'person_detected', '2026-08-03T07:01:00.000Z', '2026-08-03T07:01:15.000Z', 'demo-detector', '1.0', 0.96, '2026-08-03T07:01:15.000Z'),
('40000000-0000-4000-8000-000000000005', '30000000-0000-4000-8000-000000000003', 'person_detected', '2026-08-03T07:02:00.000Z', '2026-08-03T07:02:06.000Z', 'demo-detector', '1.0', 0.78, '2026-08-03T07:02:06.000Z'),
('40000000-0000-4000-8000-000000000006', '30000000-0000-4000-8000-000000000001', 'fall_suspected', '2026-08-03T07:03:00.000Z', '2026-08-03T07:03:09.000Z', 'demo-fall-model', '1.0', 0.61, '2026-08-03T07:03:09.000Z'),
('40000000-0000-4000-8000-000000000007', '30000000-0000-4000-8000-000000000003', 'person_detected', '2026-08-03T07:04:00.000Z', '2026-08-03T07:04:10.000Z', 'demo-detector', '1.0', 0.97, '2026-08-03T07:04:10.000Z'),
('40000000-0000-4000-8000-000000000008', '30000000-0000-4000-8000-000000000003', 'person_detected', '2026-08-03T07:04:20.000Z', '2026-08-03T07:04:27.000Z', 'demo-detector', '1.0', 0.73, '2026-08-03T07:04:27.000Z');

INSERT INTO event_persons (
    id, event_id, person_id, track_id, identity_type,
    ai_confidence, first_seen_at, last_seen_at
) VALUES
('50000000-0000-4000-8000-000000000004', '40000000-0000-4000-8000-000000000004', '10000000-0000-4000-8000-000000000002', 'track-4', 'known', 0.95, '2026-08-03T07:01:00.000Z', '2026-08-03T07:01:15.000Z'),
('50000000-0000-4000-8000-000000000005', '40000000-0000-4000-8000-000000000005', NULL, 'track-5', 'unknown', 0.78, '2026-08-03T07:02:00.000Z', '2026-08-03T07:02:06.000Z'),
('50000000-0000-4000-8000-000000000006', '40000000-0000-4000-8000-000000000006', '10000000-0000-4000-8000-000000000002', 'track-6', 'known', 0.87, '2026-08-03T07:03:00.000Z', '2026-08-03T07:03:09.000Z'),
('50000000-0000-4000-8000-000000000007', '40000000-0000-4000-8000-000000000007', '10000000-0000-4000-8000-000000000003', 'track-7', 'known', 0.97, '2026-08-03T07:04:00.000Z', '2026-08-03T07:04:10.000Z'),
('50000000-0000-4000-8000-000000000008', '40000000-0000-4000-8000-000000000008', NULL, 'track-8', 'unknown', 0.73, '2026-08-03T07:04:20.000Z', '2026-08-03T07:04:27.000Z');

INSERT INTO fall_event_details (
    id, event_id, posture, fall_confidence, immobility_duration_ms,
    algorithm_details_json
) VALUES (
    '60000000-0000-4000-8000-000000000002',
    '40000000-0000-4000-8000-000000000006',
    'transitioning', 0.61, 1200,
    '{"demo_reason":"rapid posture change"}'
);

INSERT INTO media_assets (
    id, event_id, subject_type, relative_path, mime_type,
    is_blurred, captured_at, retention_until, sha256, created_at
) VALUES
('70000000-0000-4000-8000-000000000003', '40000000-0000-4000-8000-000000000005', 'unknown_person', 'snapshots/2026/08/03/unknown-blurred-002.webp', 'image/webp', 1, '2026-08-03T07:02:02.000Z', '2026-08-10T07:02:02.000Z', 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc', '2026-08-03T07:02:03.000Z'),
('70000000-0000-4000-8000-000000000004', '40000000-0000-4000-8000-000000000006', 'fall', 'snapshots/2026/08/03/fall-002.webp', 'image/webp', 0, '2026-08-03T07:03:02.000Z', '2026-09-02T07:03:02.000Z', 'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd', '2026-08-03T07:03:03.000Z'),
('70000000-0000-4000-8000-000000000005', '40000000-0000-4000-8000-000000000008', 'unknown_person', 'snapshots/2026/08/03/unknown-blurred-003.webp', 'image/webp', 1, '2026-08-03T07:04:22.000Z', '2026-08-10T07:04:22.000Z', 'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee', '2026-08-03T07:04:23.000Z');

INSERT INTO alerts (
    id, event_id, alert_type, severity, status, assigned_user_id,
    created_at, updated_at, acknowledged_at, resolved_at
) VALUES
('80000000-0000-4000-8000-000000000003', '40000000-0000-4000-8000-000000000005', 'unknown_person', 'high', 'open', NULL, '2026-08-03T07:02:03.000Z', '2026-08-03T07:02:03.000Z', NULL, NULL),
('80000000-0000-4000-8000-000000000004', '40000000-0000-4000-8000-000000000006', 'fall', 'high', 'dismissed', '00000000-0000-4000-8000-000000000002', '2026-08-03T07:03:03.000Z', '2026-08-03T07:03:40.000Z', '2026-08-03T07:03:20.000Z', '2026-08-03T07:03:40.000Z'),
('80000000-0000-4000-8000-000000000005', '40000000-0000-4000-8000-000000000008', 'unknown_person', 'medium', 'resolved', '00000000-0000-4000-8000-000000000001', '2026-08-03T07:04:23.000Z', '2026-08-03T07:05:10.000Z', '2026-08-03T07:04:40.000Z', '2026-08-03T07:05:10.000Z');

INSERT INTO alert_actions (
    id, alert_id, user_id, action_type, previous_status,
    new_status, human_verdict, note, created_at
) VALUES
('90000000-0000-4000-8000-000000000005', '80000000-0000-4000-8000-000000000003', NULL, 'created', NULL, 'open', NULL, NULL, '2026-08-03T07:02:03.000Z'),
('90000000-0000-4000-8000-000000000006', '80000000-0000-4000-8000-000000000004', NULL, 'created', NULL, 'open', NULL, NULL, '2026-08-03T07:03:03.000Z'),
('90000000-0000-4000-8000-000000000007', '80000000-0000-4000-8000-000000000004', '00000000-0000-4000-8000-000000000002', 'acknowledged', 'open', 'acknowledged', NULL, 'Đang kiểm tra tại phòng khách', '2026-08-03T07:03:20.000Z'),
('90000000-0000-4000-8000-000000000008', '80000000-0000-4000-8000-000000000004', '00000000-0000-4000-8000-000000000002', 'verdict_recorded', NULL, NULL, 'false_positive', 'Người thân chỉ ngồi xuống nhanh', '2026-08-03T07:03:35.000Z'),
('90000000-0000-4000-8000-000000000009', '80000000-0000-4000-8000-000000000004', '00000000-0000-4000-8000-000000000002', 'dismissed', 'acknowledged', 'dismissed', NULL, NULL, '2026-08-03T07:03:40.000Z'),
('90000000-0000-4000-8000-000000000010', '80000000-0000-4000-8000-000000000005', NULL, 'created', NULL, 'open', NULL, NULL, '2026-08-03T07:04:23.000Z'),
('90000000-0000-4000-8000-000000000011', '80000000-0000-4000-8000-000000000005', '00000000-0000-4000-8000-000000000001', 'acknowledged', 'open', 'acknowledged', NULL, 'Đã xem snapshot làm mờ', '2026-08-03T07:04:40.000Z'),
('90000000-0000-4000-8000-000000000012', '80000000-0000-4000-8000-000000000005', '00000000-0000-4000-8000-000000000001', 'verdict_recorded', NULL, NULL, 'true_positive', 'Người giao hàng chưa được đăng ký', '2026-08-03T07:05:00.000Z'),
('90000000-0000-4000-8000-000000000013', '80000000-0000-4000-8000-000000000005', '00000000-0000-4000-8000-000000000001', 'resolved', 'acknowledged', 'resolved', NULL, NULL, '2026-08-03T07:05:10.000Z');

INSERT INTO inference_metrics (
    id, camera_id, evaluation_run_id, measured_at,
    window_started_at, window_ended_at, fps, latency_ms,
    precision_score, recall_score, false_positive_rate, sample_count
) VALUES
('b0000000-0000-4000-8000-000000000003', '30000000-0000-4000-8000-000000000002', NULL, '2026-08-03T07:01:00.000Z', '2026-08-03T07:00:00.000Z', '2026-08-03T07:01:00.000Z', 19.8, 55.6, NULL, NULL, NULL, 1188),
('b0000000-0000-4000-8000-000000000004', '30000000-0000-4000-8000-000000000003', NULL, '2026-08-03T07:04:30.000Z', '2026-08-03T07:03:30.000Z', '2026-08-03T07:04:30.000Z', 29.4, 33.1, NULL, NULL, NULL, 1764),
('b0000000-0000-4000-8000-000000000005', '30000000-0000-4000-8000-000000000003', 'a0000000-0000-4000-8000-000000000001', '2026-08-03T05:10:00.000Z', '2026-08-03T05:00:00.000Z', '2026-08-03T05:10:00.000Z', 28.6, 35.0, 0.90, 0.87, 0.06, 500);

COMMIT;
