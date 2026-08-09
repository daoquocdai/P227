from datetime import UTC, datetime
from typing import Any

from src.database import database_connection
from src.services.sqlite_event_repository import SQLiteEventRepository


class OverviewService:
    def __init__(self, event_repository: SQLiteEventRepository | None = None) -> None:
        self._events = event_repository or SQLiteEventRepository()

    def get_overview(self, runtime=None) -> dict[str, Any]:
        now = datetime.now().astimezone()
        alerts = self._events.list_alerts()
        today_alerts = [item for item in alerts if self._is_today(item["timestamp"], now)]
        pending = [item for item in today_alerts if item["status"] in {"pending", "checking", "need_help"}]

        with database_connection() as connection:
            camera_rows = connection.execute(
                """SELECT c.id, c.name, c.source_type, c.source_reference, c.location_label,
                          c.operational_status, c.last_seen_at, cs.source_kind, cs.playback_path
                   FROM cameras c LEFT JOIN camera_sources cs ON cs.camera_id = c.id
                   WHERE c.is_active = 1 ORDER BY c.name"""
            ).fetchall()
            recognized_today = connection.execute(
                """SELECT count(DISTINCT ep.person_id)
                   FROM event_persons ep
                   JOIN events e ON e.id = ep.event_id
                   WHERE ep.person_id IS NOT NULL AND date(e.occurred_at) = date('now', 'localtime')"""
            ).fetchone()[0]

        cameras = [self._camera(row, runtime) for row in camera_rows]
        online_count = sum(camera["status"] == "online" for camera in cameras)
        current_alert = pending[0] if pending else None
        safe = current_alert is None

        return {
            "generated_at": now.isoformat(),
            "system_status": "safe" if safe else "attention",
            "headline": "Ngôi nhà đang an toàn" if safe else "Có tình huống cần bạn chú ý",
            "summary": (
                f"Hệ thống đang theo dõi {online_count}/{len(cameras)} camera và chưa có cảnh báo chờ xử lý."
                if safe
                else f"Có {len(pending)} cảnh báo hôm nay đang chờ bạn kiểm tra."
            ),
            "metrics": {
                "online_cameras": online_count,
                "total_cameras": len(cameras),
                "events_today": len(today_alerts),
                "pending_alerts": len(pending),
                "recognized_people_today": recognized_today,
            },
            "current_alert": current_alert,
            "cameras": cameras,
            "insights": self._insights(online_count, len(cameras), len(pending), recognized_today),
        }

    @staticmethod
    def _camera(row, runtime=None) -> dict[str, Any]:
        public_id = row["name"] if row["name"].startswith("camera-") else row["id"]
        runtime_state = runtime.get_status(public_id) if runtime is not None else None
        runtime_last_frame = runtime_state["last_frame_at"] if runtime_state is not None else None
        return {
            "id": public_id,
            "name": row["location_label"] or row["name"],
            "location": row["location_label"],
            "status": runtime_state["status"] if runtime_state is not None else "offline",
            "last_seen_at": (
                datetime.fromtimestamp(runtime_last_frame, UTC).isoformat()
                if runtime_last_frame is not None
                else row["last_seen_at"]
            ),
            "source_type": row["source_kind"] or row["source_type"],
            "playback_url": f"/{row['playback_path'].lstrip('/')}" if row["playback_path"] else None,
            "stream_url": f"/api/v1/cameras/{public_id}/stream",
            "stream_ready": runtime_state is not None and runtime_state["status"] == "online",
        }

    @staticmethod
    def _is_today(value: str, now: datetime) -> bool:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().date() == now.date()
        except ValueError:
            return False

    @staticmethod
    def _insights(online: int, total: int, pending: int, recognized: int) -> list[str]:
        return [
            "Không có cảnh báo nào đang chờ xử lý" if pending == 0 else f"{pending} cảnh báo cần được kiểm tra",
            f"{online}/{total} camera đang hoạt động ổn định",
            f"{recognized} người thân đã được nhận diện hôm nay",
        ]


overview_service = OverviewService()
