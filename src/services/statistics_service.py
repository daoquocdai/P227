from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.config import get_settings
from src.database import database_connection

LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
ALERT_TYPES = ("fall", "unknown_person")
logger = logging.getLogger(__name__)


def _latest_action_cte() -> str:
    return """
        WITH target_alerts AS (
            SELECT a.id, a.alert_type, a.created_at, e.camera_id, e.occurred_at
            FROM events e JOIN alerts a ON a.event_id = e.id
            WHERE e.occurred_at >= ? AND e.occurred_at < ?
        ),
        ranked_actions AS (
            SELECT aa.*,
                   row_number() OVER (
                       PARTITION BY aa.alert_id ORDER BY aa.created_at DESC, aa.id DESC
                   ) AS action_rank
            FROM alert_actions aa JOIN target_alerts ta ON ta.id = aa.alert_id
        ),
        alert_data AS (
            SELECT ta.id, ta.alert_type, ta.created_at, ta.camera_id, ta.occurred_at,
                   ra.action_type, ra.human_verdict, ra.note,
                   CASE
                       WHEN ra.human_verdict = 'false_positive' THEN 'false'
                       WHEN ra.human_verdict = 'true_positive'
                            OR ra.action_type IN ('resolved', 'dismissed') THEN 'true'
                       ELSE NULL
                   END AS review_result,
                   (SELECT min(first_action.created_at)
                    FROM alert_actions first_action
                    WHERE first_action.alert_id = ta.id
                      AND first_action.action_type <> 'created') AS first_response_at
            FROM target_alerts ta
            LEFT JOIN ranked_actions ra ON ra.alert_id = ta.id AND ra.action_rank = 1
        )
    """


class StatisticsService:
    @staticmethod
    def range_for(
        period: str,
        start: datetime | None,
        end: datetime | None,
        *,
        now: datetime | None = None,
    ) -> tuple[datetime, datetime]:
        current = (now or datetime.now(UTC)).astimezone(LOCAL_TZ)
        if period == "custom":
            if start is None or end is None or start.tzinfo is None or end.tzinfo is None:
                raise ValueError("Khoảng thời gian tùy chọn phải có múi giờ")
            range_start, range_end = start.astimezone(UTC), end.astimezone(UTC)
            if range_start >= range_end:
                raise ValueError("Khoảng thời gian tùy chọn không hợp lệ")
            if range_end - range_start > timedelta(days=90):
                raise ValueError("Khoảng thời gian tùy chọn tối đa là 90 ngày")
            return range_start, range_end

        days = {"today": 1, "7d": 7, "30d": 30}.get(period)
        if days is None:
            raise ValueError("Khoảng thời gian không được hỗ trợ")
        first_day = current.date() - timedelta(days=days - 1)
        local_start = datetime.combine(first_day, time.min, tzinfo=LOCAL_TZ)
        return local_start.astimezone(UTC), current.astimezone(UTC)

    def get_statistics(
        self,
        start: datetime,
        end: datetime,
        *,
        period: str = "custom",
        runtime=None,
    ) -> dict[str, Any]:
        duration = end - start
        previous_start, previous_end = start - duration, start
        alert_bucket_unit = self._alert_bucket_unit(period, start, end)
        with database_connection() as connection:
            current = self._kpis(connection, start, end)
            previous = self._kpis(connection, previous_start, previous_end)
            timeline = self._complete_timeline(
                self._timeline(connection, start, end, alert_bucket_unit),
                start,
                end,
                alert_bucket_unit,
            )
            cameras = self._camera_distribution(connection, start, end)
            reasons = self._false_alarm_reasons(connection, start, end)
            hub = self._hub_metrics(connection)
            persisted_cameras = self._persisted_camera_metrics(connection)
            performance, performance_series = self._performance_timeline(connection, start, end)
        camera_metrics = self._current_camera_metrics(persisted_cameras, runtime)
        return {
            "range": {"start": start.isoformat(), "end": end.isoformat(), "timezone": str(LOCAL_TZ)},
            "kpis": self._with_trends(current, previous),
            "alert_bucket": {"unit": alert_bucket_unit, "timezone": str(LOCAL_TZ)},
            "alert_timeline": timeline,
            "camera_distribution": cameras,
            "false_alarm_reasons": reasons,
            "hub_metrics": hub,
            "camera_metrics": camera_metrics,
            "performance_timeline": performance,
            "performance_series": performance_series,
            "threshold_alerts": self._threshold_alerts(hub, camera_metrics),
        }

    @staticmethod
    def _params(start: datetime, end: datetime) -> tuple[str, str]:
        return start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()

    @classmethod
    def _kpis(cls, connection, start: datetime, end: datetime) -> dict[str, float | int | None]:
        row = connection.execute(
            _latest_action_cte()
            + """
              SELECT count(*) AS total,
                     count(CASE WHEN review_result = 'true' THEN 1 END) AS true_count,
                     count(CASE WHEN review_result = 'false' THEN 1 END) AS false_count,
                     count(CASE WHEN review_result IS NULL THEN 1 END) AS unconfirmed_count,
                     avg(CASE WHEN first_response_at IS NOT NULL THEN
                         (julianday(first_response_at) - julianday(created_at)) * 86400000 END
                     ) AS response_ms
              FROM alert_data""",
            cls._params(start, end),
        ).fetchone()
        reviewed = row["true_count"] + row["false_count"]
        return {
            "total_alerts": row["total"],
            "true_alerts": row["true_count"],
            "false_alerts": row["false_count"],
            "unconfirmed_alerts": row["unconfirmed_count"],
            "false_alarm_rate": row["false_count"] / reviewed if reviewed else None,
            "average_response_ms": row["response_ms"],
        }

    @staticmethod
    def _with_trends(current: dict, previous: dict) -> dict[str, dict]:
        lower_is_better = {
            "false_alerts",
            "unconfirmed_alerts",
            "false_alarm_rate",
            "average_response_ms",
        }
        result = {}
        for key, value in current.items():
            old = previous[key]
            change = None if value is None or old in {None, 0} else (value - old) / old * 100
            improved = None if change is None else (change < 0 if key in lower_is_better else change > 0)
            result[key] = {"value": value, "change_percent": change, "improved": improved}
        return result

    @staticmethod
    def _alert_bucket_unit(period: str, start: datetime, end: datetime) -> str:
        if period == "today" or (period == "custom" and end - start <= timedelta(days=2)):
            return "hour"
        return "day"

    @classmethod
    def _timeline(
        cls,
        connection,
        start: datetime,
        end: datetime,
        bucket_unit: str,
    ) -> list[dict]:
        bucket_sql = (
            "strftime('%Y-%m-%dT%H:00:00', occurred_at, '+7 hours') || '+07:00'"
            if bucket_unit == "hour"
            else "date(occurred_at, '+7 hours') || 'T00:00:00+07:00'"
        )
        rows = connection.execute(
            _latest_action_cte()
            + f"""
              SELECT {bucket_sql} AS bucket_start, alert_type, count(*) AS total,
                     count(CASE WHEN review_result = 'true' THEN 1 END) AS confirmed,
                     count(CASE WHEN review_result = 'false' THEN 1 END) AS false_alarms
               FROM alert_data
               GROUP BY bucket_start, alert_type ORDER BY bucket_start, alert_type""",
            cls._params(start, end),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _complete_timeline(
        rows: list[dict],
        start: datetime,
        end: datetime,
        bucket_unit: str,
    ) -> list[dict]:
        indexed = {(row["bucket_start"], row["alert_type"]): row for row in rows}
        result = []
        local_start = start.astimezone(LOCAL_TZ)
        local_end = (end - timedelta(microseconds=1)).astimezone(LOCAL_TZ)
        if bucket_unit == "hour":
            current = local_start.replace(minute=0, second=0, microsecond=0)
            last = local_end.replace(minute=0, second=0, microsecond=0)
            step = timedelta(hours=1)
        else:
            current = datetime.combine(local_start.date(), time.min, tzinfo=LOCAL_TZ)
            last = datetime.combine(local_end.date(), time.min, tzinfo=LOCAL_TZ)
            step = timedelta(days=1)
        while current <= last:
            bucket_start = current.isoformat()
            for alert_type in ALERT_TYPES:
                result.append(
                    indexed.get(
                        (bucket_start, alert_type),
                        {
                            "bucket_start": bucket_start,
                            "alert_type": alert_type,
                            "total": 0,
                            "confirmed": 0,
                            "false_alarms": 0,
                        },
                    )
                )
            current += step
        return result

    @classmethod
    def _camera_distribution(cls, connection, start: datetime, end: datetime) -> list[dict]:
        rows = connection.execute(
            _latest_action_cte()
            + """
              SELECT c.id, c.name, c.location_label, count(ad.id) AS alert_count,
                     count(CASE WHEN ad.review_result = 'false' THEN 1 END) AS false_count,
                     count(CASE WHEN ad.review_result IS NOT NULL THEN 1 END) AS reviewed_count
              FROM cameras c
              LEFT JOIN alert_data ad ON ad.camera_id = c.id
              GROUP BY c.id ORDER BY alert_count DESC, c.name""",
            cls._params(start, end),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "location": row["location_label"],
                "alert_count": row["alert_count"],
                "false_alarm_rate": (
                    row["false_count"] / row["reviewed_count"] if row["reviewed_count"] else None
                ),
            }
            for row in rows
        ]

    @classmethod
    def _false_alarm_reasons(cls, connection, start: datetime, end: datetime) -> list[dict]:
        rows = connection.execute(
            _latest_action_cte()
            + """
              SELECT trim(note) AS note, count(*) AS count FROM alert_data
              WHERE review_result = 'false' AND note IS NOT NULL AND trim(note) <> ''
              GROUP BY lower(trim(note)) ORDER BY count DESC, note LIMIT 5""",
            cls._params(start, end),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _hub_metrics(connection) -> dict | None:
        row = connection.execute(
            """SELECT measured_at, process_cpu_percent, process_rss_mb,
                      host_memory_total_mb, host_memory_used_percent, disk_used_percent
               FROM hub_metrics ORDER BY measured_at DESC, id DESC LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["data_source"] = "persisted"
        result["is_stale"] = StatisticsService._is_stale(result["measured_at"])
        return result

    @staticmethod
    def _persisted_camera_metrics(connection) -> list[dict]:
        rows = connection.execute(
            """SELECT c.id, c.name, c.location_label, c.is_active, c.vision_enabled,
                      cs.source_kind,
                      ocm.measured_at, ocm.camera_status, ocm.last_seen_at, ocm.raw_fps,
                      ocm.vision_status, ocm.vision_fps, ocm.vision_processing_latency_ms,
                      ocm.vision_drop_ratio, ocm.pending, ocm.max_pending,
                      ocm.vision_frames_offered, ocm.vision_frames_overwritten
               FROM cameras c
               LEFT JOIN camera_sources cs ON cs.camera_id = c.id
               LEFT JOIN operational_camera_metrics ocm ON ocm.id = (
                   SELECT newest.id FROM operational_camera_metrics newest
                   WHERE newest.camera_id = c.id
                   ORDER BY newest.measured_at DESC, newest.id DESC LIMIT 1
               )
               ORDER BY c.name"""
        ).fetchall()
        return [dict(row) for row in rows]

    @classmethod
    def _current_camera_metrics(cls, persisted: list[dict], runtime) -> list[dict]:
        if runtime is None:
            return [cls._persisted_current_metric(camera) for camera in persisted]

        measured_at = datetime.now(UTC).isoformat(timespec="milliseconds")
        current = []
        for camera in persisted:
            public_id = camera["name"] if camera["name"].startswith("camera-") else camera["id"]
            try:
                camera_state = runtime.camera.get_status(public_id)
                vision_state = runtime.vision.get_status(public_id)
            except Exception:  # noqa: BLE001 - telemetry must not break the Statistics page
                logger.exception("Current telemetry failed camera=%s", camera["id"])
                current.append(cls._persisted_current_metric(camera))
                continue

            camera_state = camera_state if isinstance(camera_state, dict) else {}
            vision_state = vision_state if isinstance(vision_state, dict) else {}
            raw_status = camera_state.get("status")
            if not camera["is_active"]:
                camera_status = "disabled"
            else:
                camera_status = {
                    "online": "online",
                    "connecting": "waiting",
                    "error": "error",
                    "ended": "ended",
                }.get(raw_status, "disconnected")

            last_frame = camera_state.get("last_frame_at")
            last_seen_at = (
                datetime.fromtimestamp(float(last_frame), UTC).isoformat(timespec="milliseconds")
                if last_frame
                else None
            )
            raw_fps = camera_state.get("capture_fps") if camera_status == "online" else None
            vision_enabled = bool(camera["vision_enabled"] and vision_state.get("enabled", True))
            vision_status = vision_state.get("status", "waiting_for_source") if vision_enabled else "disabled"
            realtime = vision_state.get("realtime") if vision_enabled else None
            realtime = realtime if isinstance(realtime, dict) else {}
            processed = int(realtime.get("vision_frames_processed") or 0)
            offered = int(realtime.get("vision_frames_offered") or 0)
            current.append(
                {
                    "id": camera["id"],
                    "name": camera["name"],
                    "location_label": camera["location_label"],
                    "source_kind": camera["source_kind"],
                    "is_active": bool(camera["is_active"]),
                    "measured_at": measured_at,
                    "historical_sample_at": camera["measured_at"],
                    "data_source": "runtime",
                    "is_stale": False,
                    "camera_status": camera_status,
                    "last_seen_at": last_seen_at,
                    "raw_fps": raw_fps,
                    "vision_status": vision_status,
                    "vision_fps": realtime.get("vision_fps") if vision_enabled and processed >= 2 else None,
                    "vision_processing_latency_ms": (
                        realtime.get("vision_processing_latency_ms")
                        if vision_enabled and processed >= 1
                        else None
                    ),
                    "vision_drop_ratio": (
                        realtime.get("vision_drop_ratio") if vision_enabled and offered > 0 else None
                    ),
                    "pending": realtime.get("pending") if vision_enabled else None,
                    "max_pending": realtime.get("max_pending") if vision_enabled else None,
                    "vision_frames_offered": offered if vision_enabled else None,
                    "vision_frames_overwritten": (
                        realtime.get("vision_frames_overwritten") if vision_enabled else None
                    ),
                }
            )
        return current

    @classmethod
    def _persisted_current_metric(cls, camera: dict) -> dict:
        result = dict(camera)
        result["historical_sample_at"] = result.pop("measured_at")
        result["measured_at"] = result["historical_sample_at"]
        result["data_source"] = "persisted" if result["historical_sample_at"] else "none"
        result["is_stale"] = cls._is_stale(result["historical_sample_at"])
        if not result["is_active"]:
            result["camera_status"] = "disabled"
        elif result["camera_status"] == "connecting":
            result["camera_status"] = "waiting"
        elif result["camera_status"] == "offline" or result["camera_status"] is None:
            result["camera_status"] = "disconnected"
        return result

    @staticmethod
    def _is_stale(measured_at: str | None) -> bool:
        if not measured_at:
            return True
        try:
            timestamp = datetime.fromisoformat(measured_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        stale_after = max(get_settings().metrics_collection_interval_seconds * 2, 60)
        return datetime.now(UTC) - timestamp.astimezone(UTC) > timedelta(seconds=stale_after)

    @classmethod
    def _performance_timeline(
        cls,
        connection,
        start: datetime,
        end: datetime,
    ) -> tuple[list[dict], list[dict]]:
        params = cls._params(start, end)
        series_rows = connection.execute(
            """SELECT c.id AS camera_id, c.name AS camera_name, count(ocm.id) AS sample_count
               FROM cameras c
               LEFT JOIN operational_camera_metrics ocm
                 ON ocm.camera_id = c.id AND ocm.measured_at >= ? AND ocm.measured_at < ?
                AND (ocm.vision_fps IS NOT NULL OR ocm.vision_processing_latency_ms IS NOT NULL)
               GROUP BY c.id, c.name""",
            params,
        ).fetchall()
        max_samples = max((row["sample_count"] for row in series_rows), default=0)
        bucket_seconds = 0
        if max_samples > 120:
            seconds = max((end - start).total_seconds(), 1)
            bucket_seconds = max(60, math.ceil(seconds / 120 / 60) * 60)
            rows = connection.execute(
                """WITH bucketed AS (
                       SELECT camera_id,
                              strftime('%Y-%m-%dT%H:%M:%SZ',
                                (CAST(strftime('%s', measured_at) AS INTEGER) / ?) * ?, 'unixepoch') AS bucket_start,
                              avg(raw_fps) AS raw_fps, avg(vision_fps) AS vision_fps,
                              avg(vision_processing_latency_ms) AS vision_processing_latency_ms,
                              avg(vision_drop_ratio) AS vision_drop_ratio,
                              max(max_pending) AS max_pending, count(*) AS sample_count
                       FROM operational_camera_metrics
                       WHERE measured_at >= ? AND measured_at < ?
                         AND (vision_fps IS NOT NULL OR vision_processing_latency_ms IS NOT NULL)
                       GROUP BY camera_id, bucket_start
                   ), ranked AS (
                       SELECT b.*, c.name AS camera_name,
                              row_number() OVER (PARTITION BY b.camera_id ORDER BY b.bucket_start DESC) AS point_rank
                       FROM bucketed b JOIN cameras c ON c.id = b.camera_id
                   )
                   SELECT camera_id, camera_name, bucket_start AS measured_at, raw_fps, vision_fps,
                          vision_processing_latency_ms, vision_drop_ratio, max_pending,
                          sample_count, ? AS bucket_seconds
                   FROM ranked WHERE point_rank <= 120 ORDER BY measured_at, camera_name""",
                (bucket_seconds, bucket_seconds, *params, bucket_seconds),
            ).fetchall()
        else:
            rows = connection.execute(
                """WITH ranked AS (
                       SELECT ocm.*, c.name AS camera_name,
                              row_number() OVER (
                                PARTITION BY ocm.camera_id ORDER BY ocm.measured_at DESC, ocm.id DESC
                              ) AS point_rank
                       FROM operational_camera_metrics ocm
                       JOIN cameras c ON c.id = ocm.camera_id
                       WHERE ocm.measured_at >= ? AND ocm.measured_at < ?
                         AND (ocm.vision_fps IS NOT NULL OR ocm.vision_processing_latency_ms IS NOT NULL)
                   )
                   SELECT camera_id, camera_name, measured_at, raw_fps, vision_fps,
                          vision_processing_latency_ms, vision_drop_ratio, max_pending,
                          1 AS sample_count, 0 AS bucket_seconds
                   FROM ranked WHERE point_rank <= 120 ORDER BY measured_at, camera_name""",
                params,
            ).fetchall()
        points = [dict(row) for row in rows]
        bucket_counts: dict[str, int] = {}
        for point in points:
            bucket_counts[point["camera_id"]] = bucket_counts.get(point["camera_id"], 0) + 1
        series = [
            {
                "camera_id": row["camera_id"],
                "camera_name": row["camera_name"],
                "sample_count": row["sample_count"],
                "bucket_count": bucket_counts.get(row["camera_id"], 0),
                "bucket_seconds": bucket_seconds,
            }
            for row in sorted(series_rows, key=lambda item: (-item["sample_count"], item["camera_name"]))
        ]
        return points, series

    @staticmethod
    def _threshold_alerts(hub: dict | None, cameras: list[dict]) -> list[dict]:
        alerts = []
        if hub:
            reasons = []
            if hub["process_cpu_percent"] is not None and hub["process_cpu_percent"] > 90:
                reasons.append("CPU tiến trình backend trên 90%")
            if hub["host_memory_used_percent"] is not None and hub["host_memory_used_percent"] > 90:
                reasons.append("RAM máy chủ trên 90%")
            if hub["disk_used_percent"] is not None and hub["disk_used_percent"] > 90:
                reasons.append("Dung lượng đĩa trên 90%")
            if reasons:
                alerts.append({"scope": "hub", "id": "hub", "name": "Local Hub", "reasons": reasons})
        for camera in cameras:
            reasons = []
            if camera["camera_status"] in {"disconnected", "error"}:
                reasons.append("Camera mất kết nối")
            if camera["max_pending"] is not None and camera["max_pending"] > 1:
                reasons.append("Hàng đợi Vision vượt giới hạn 1")
            if reasons:
                alerts.append(
                    {"scope": "camera", "id": camera["id"], "name": camera["name"], "reasons": reasons}
                )
        return alerts


statistics_service = StatisticsService()
