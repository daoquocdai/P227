"""Create an isolated, deterministic dataset for visual QA of the Statistics page."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.config import get_settings
from src.database import database_connection, initialize_database


def main() -> None:
    if get_settings().app_env != "test":
        raise RuntimeError("This showcase seed only runs with APP_ENV=test")
    initialize_database()
    now = datetime.now(UTC)
    cameras = [
        (str(uuid4()), "camera-showcase-online", "Phòng khách", "online"),
        (str(uuid4()), "camera-showcase-offline", "Phòng ngủ", "offline"),
        (str(uuid4()), "camera-showcase-error", "Hành lang", "error"),
    ]
    with database_connection() as connection:
        for camera_id, name, location, status in cameras:
            connection.execute(
                """INSERT INTO cameras
                   (id,name,source_type,source_reference,location_label,operational_status,last_seen_at,is_active,vision_enabled)
                   VALUES (?,?,'video_file',?,?,?, ?,0,0)""",
                (camera_id, name, f"videos/{name}.mp4", location, status, now.isoformat()),
            )
        for index in range(10):
            camera_id = cameras[0][0] if index < 8 else cameras[index - 7][0]
            occurred = now - timedelta(days=6 - index % 7, hours=index)
            event_id, alert_id = str(uuid4()), str(uuid4())
            alert_type = "fall" if index % 2 == 0 else "unknown_person"
            event_type = "fall_suspected" if alert_type == "fall" else "person_detected"
            connection.execute(
                """INSERT INTO events
                   (id,camera_id,event_type,occurred_at,ai_model_name,ai_model_version,ai_confidence,metadata_json)
                   VALUES (?,?,?,?, 'showcase-model','1.0',0.91,'{}')""",
                (event_id, camera_id, event_type, occurred.isoformat()),
            )
            if alert_type == "unknown_person":
                connection.execute(
                    """INSERT INTO event_persons
                       (id,event_id,track_id,identity_type,ai_confidence,first_seen_at,last_seen_at)
                       VALUES (?,?,?,'unknown',0.91,?,?)""",
                    (str(uuid4()), event_id, f"track-{index}", occurred.isoformat(), occurred.isoformat()),
                )
            status = "open" if index < 6 else "resolved" if index < 8 else "dismissed"
            connection.execute(
                "INSERT INTO alerts (id,event_id,alert_type,severity,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (alert_id, event_id, alert_type, "high", status, occurred.isoformat(), occurred.isoformat()),
            )
            connection.execute(
                "INSERT INTO alert_actions (id,alert_id,action_type,new_status,created_at) VALUES (?,?,'created','open',?)",
                (str(uuid4()), alert_id, occurred.isoformat()),
            )
            if index >= 6:
                verdict = "true_positive" if index < 8 else "false_positive"
                action = "verdict_recorded"
                note = None if verdict == "true_positive" else "Bóng đổ"
                connection.execute(
                    """INSERT INTO alert_actions
                       (id,alert_id,action_type,previous_status,new_status,human_verdict,note,created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (str(uuid4()), alert_id, action, "open", status, verdict, note, (occurred + timedelta(minutes=2)).isoformat()),
                )
        for index in range(14):
            measured = now - timedelta(hours=13 - index)
            connection.execute(
                """INSERT INTO inference_metrics
                   (id,camera_id,measured_at,fps,latency_ms,sample_count)
                   VALUES (?,?,?,?,?,?)""",
                (str(uuid4()), cameras[0][0], measured.isoformat(), 22 + index % 4, 42 + index * 1.5, 300),
            )
        connection.execute(
            """INSERT INTO device_metrics
               (id,camera_id,measured_at,ram_usage_mb,ram_total_mb,cpu_usage_percent,ping_ms,disk_usage_percent)
               VALUES (?,?,?,?,?,?,?,?)""",
            (str(uuid4()), cameras[0][0], now.isoformat(), 620, 2048, 36, 18, 44),
        )
        connection.execute(
            """INSERT INTO device_metrics
               (id,camera_id,measured_at,ram_usage_mb,ram_total_mb,cpu_usage_percent,ping_ms,disk_usage_percent)
               VALUES (?,NULL,?,?,?,?,?,?)""",
            (str(uuid4()), now.isoformat(), 840, 16384, 24, 3, 51),
        )
    print(f"Statistics showcase ready: {os.getenv('DATABASE_URL')}")


if __name__ == "__main__":
    main()
