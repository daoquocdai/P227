-- Named parameters use SQLite's :parameter syntax.

-- 1. When and where was a person seen most recently?
SELECT ep.last_seen_at, c.id AS camera_id, c.name AS camera_name, c.location_label
FROM event_persons AS ep
JOIN events AS e ON e.id = ep.event_id
JOIN cameras AS c ON c.id = e.camera_id
WHERE ep.person_id = :person_id
ORDER BY ep.last_seen_at DESC
LIMIT 1;

-- 2. Where did a person appear during a UTC time range?
SELECT ep.first_seen_at, ep.last_seen_at, c.id AS camera_id,
       c.name AS camera_name, c.location_label, e.id AS event_id
FROM event_persons AS ep
JOIN events AS e ON e.id = ep.event_id
JOIN cameras AS c ON c.id = e.camera_id
WHERE ep.person_id = :person_id
  AND ep.last_seen_at >= :from_utc
  AND ep.first_seen_at < :to_utc
ORDER BY ep.first_seen_at;

-- 3. Unknown-person appearances during a UTC time range.
SELECT ep.first_seen_at, ep.last_seen_at, e.id AS event_id,
       c.name AS camera_name, c.location_label, ma.relative_path AS blurred_snapshot
FROM event_persons AS ep
JOIN events AS e ON e.id = ep.event_id
JOIN cameras AS c ON c.id = e.camera_id
LEFT JOIN media_assets AS ma
       ON ma.event_id = e.id AND ma.subject_type = 'unknown_person'
WHERE ep.identity_type = 'unknown'
  AND ep.last_seen_at >= :from_utc
  AND ep.first_seen_at < :to_utc
ORDER BY ep.first_seen_at;

-- 4. Number of fall alerts today in UTC.
SELECT count(*) AS fall_alert_count
FROM alerts
WHERE alert_type = 'fall'
  AND created_at >= strftime('%Y-%m-%dT00:00:00.000Z', 'now')
  AND created_at < strftime('%Y-%m-%dT00:00:00.000Z', 'now', '+1 day');

-- 5. Alerts that have not been acknowledged.
SELECT a.*, c.name AS camera_name, c.location_label
FROM alerts AS a
JOIN events AS e ON e.id = a.event_id
JOIN cameras AS c ON c.id = e.camera_id
WHERE a.status = 'open'
ORDER BY a.created_at DESC;

-- 6. Cameras considered offline. The caller supplies an ISO UTC cutoff.
SELECT id, name, location_label, operational_status, last_seen_at
FROM cameras
WHERE is_active = 1
  AND (operational_status <> 'online' OR last_seen_at IS NULL OR last_seen_at < :offline_cutoff)
ORDER BY name;

-- 7. False-alert rate using only the latest human verdict per alert.
WITH ranked_verdicts AS (
    SELECT alert_id, human_verdict,
           row_number() OVER (
               PARTITION BY alert_id ORDER BY created_at DESC, id DESC
           ) AS verdict_rank
    FROM alert_actions
    WHERE human_verdict IS NOT NULL
)
SELECT sum(CASE WHEN human_verdict = 'false_positive' THEN 1 ELSE 0 END) AS false_alerts,
       count(*) AS reviewed_alerts,
       CASE WHEN count(*) = 0 THEN NULL
            ELSE 1.0 * sum(CASE WHEN human_verdict = 'false_positive' THEN 1 ELSE 0 END) / count(*)
       END AS false_alert_rate
FROM ranked_verdicts
WHERE verdict_rank = 1;

-- 8. Latest FPS and latency for every camera.
WITH ranked_metrics AS (
    SELECT im.*,
           row_number() OVER (
               PARTITION BY camera_id ORDER BY measured_at DESC, id DESC
           ) AS metric_rank
    FROM inference_metrics AS im
    WHERE fps IS NOT NULL OR latency_ms IS NOT NULL
)
SELECT c.id AS camera_id, c.name, rm.measured_at, rm.fps, rm.latency_ms
FROM cameras AS c
LEFT JOIN ranked_metrics AS rm
       ON rm.camera_id = c.id AND rm.metric_rank = 1
ORDER BY c.name;

-- 9. Full handling history for one alert.
SELECT aa.created_at, aa.action_type, aa.previous_status, aa.new_status,
       aa.human_verdict, aa.note, u.display_name AS performed_by
FROM alert_actions AS aa
LEFT JOIN users AS u ON u.id = aa.user_id
WHERE aa.alert_id = :alert_id
ORDER BY aa.created_at, aa.id;

-- 10. Snapshots whose retention period has expired.
SELECT id, relative_path, retention_until
FROM media_assets
WHERE retention_until <= :now_utc
ORDER BY retention_until;

-- 11. List all explicit permissions for one caregiver.
SELECT permission_key, is_granted, updated_at
FROM user_permissions
WHERE user_id = :user_id
ORDER BY permission_key;

-- 12. Change one caregiver permission. Admin authorization is checked by the
-- caller; inactive caregivers are protected by the EXISTS condition.
UPDATE user_permissions
SET is_granted = :is_granted,
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE user_id = :user_id
  AND permission_key = :permission_key
  AND EXISTS (
      SELECT 1 FROM users
      WHERE users.id = user_permissions.user_id
        AND users.role = 'caregiver'
        AND users.is_active = 1
  );
