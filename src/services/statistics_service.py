from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

from src.database import database_connection


class StatisticsService:
    def get_statistics(self, start: datetime, end: datetime) -> dict[str, Any]:
        duration = end - start
        previous_start, previous_end = start - duration, start
        with database_connection() as connection:
            current = self._kpis(connection, start, end)
            previous = self._kpis(connection, previous_start, previous_end)
            timeline = self._complete_timeline(self._timeline(connection, start, end), start, end)
            cameras = self._camera_distribution(connection, start, end)
            reasons = self._false_alarm_reasons(connection, start, end)
            devices = self._device_status(connection)
            performance = self._performance_timeline(connection, start, end)
        return {
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "kpis": self._with_trends(current, previous),
            "alert_timeline": timeline,
            "camera_distribution": cameras,
            "false_alarm_reasons": reasons,
            "devices": devices,
            "performance_timeline": performance,
            "threshold_alerts": self._threshold_alerts(devices),
        }

    @staticmethod
    def range_for(period: str, start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
        now = datetime.now(UTC)
        if period == "custom":
            if start is None or end is None or start >= end:
                raise ValueError("Khoảng thời gian tùy chọn không hợp lệ")
            return start.astimezone(UTC), end.astimezone(UTC)
        days = {"today": 1, "7d": 7, "30d": 30}.get(period)
        if days is None:
            raise ValueError("Khoảng thời gian không được hỗ trợ")
        if period == "today":
            return now.replace(hour=0, minute=0, second=0, microsecond=0), now
        first_day = (now - timedelta(days=days - 1)).date()
        return datetime.combine(first_day, time.min, tzinfo=UTC), now

    @staticmethod
    def _kpis(connection, start: datetime, end: datetime) -> dict[str, float]:
        params = (start.isoformat(), end.isoformat())
        row = connection.execute(
            """WITH alert_data AS (
                   SELECT a.*,
                          (SELECT aa.human_verdict FROM alert_actions aa
                           WHERE aa.alert_id=a.id AND aa.human_verdict IS NOT NULL
                           ORDER BY aa.created_at DESC,aa.id DESC LIMIT 1) verdict
                   FROM alerts a JOIN events e ON e.id=a.event_id
                   WHERE e.occurred_at>=? AND e.occurred_at<?
               )
               SELECT count(*) total,
                      count(CASE WHEN verdict='true_positive' THEN 1 END) true_count,
                      count(CASE WHEN verdict='false_positive' THEN 1 END) false_count,
                      count(CASE WHEN verdict IS NULL OR status='open' THEN 1 END) unconfirmed_count,
                      avg(CASE WHEN a.acknowledged_at IS NOT NULL
                          THEN (julianday(a.acknowledged_at)-julianday(a.created_at))*86400000 END) response_ms
               FROM alert_data a""",
            params,
        ).fetchone()
        inference_rate = connection.execute(
            "SELECT avg(false_positive_rate) FROM inference_metrics WHERE measured_at>=? AND measured_at<?",
            params,
        ).fetchone()[0]
        confirmed = row["true_count"] + row["false_count"]
        direct_rate = row["false_count"] / confirmed if confirmed else None
        return {
            "total_alerts": row["total"],
            "true_alerts": row["true_count"],
            "false_alerts": row["false_count"],
            "unconfirmed_alerts": row["unconfirmed_count"],
            "false_alarm_rate": direct_rate if direct_rate is not None else (inference_rate or 0),
            "average_response_ms": row["response_ms"] or 0,
        }

    @staticmethod
    def _with_trends(current: dict[str, float], previous: dict[str, float]) -> dict[str, dict[str, float | None]]:
        lower_is_better = {"false_alerts", "unconfirmed_alerts", "false_alarm_rate", "average_response_ms"}
        result = {}
        for key, value in current.items():
            old = previous[key]
            change = None if old == 0 else (value - old) / old * 100
            improved = None if change is None else (change < 0 if key in lower_is_better else change > 0)
            result[key] = {"value": value, "change_percent": change, "improved": improved}
        return result

    @staticmethod
    def _timeline(connection, start: datetime, end: datetime) -> list[dict]:
        rows = connection.execute(
            """WITH alert_data AS (
                   SELECT date(e.occurred_at) day,a.alert_type,
                          (SELECT aa.human_verdict FROM alert_actions aa
                           WHERE aa.alert_id=a.id AND aa.human_verdict IS NOT NULL
                           ORDER BY aa.created_at DESC,aa.id DESC LIMIT 1) verdict
                   FROM alerts a JOIN events e ON e.id=a.event_id
                   WHERE e.occurred_at>=? AND e.occurred_at<?
               )
               SELECT day,alert_type,count(*) total,
                      count(CASE WHEN verdict='true_positive' THEN 1 END) confirmed,
                      count(CASE WHEN verdict='false_positive' THEN 1 END) false_alarms
               FROM alert_data GROUP BY day,alert_type ORDER BY day""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _complete_timeline(rows: list[dict], start: datetime, end: datetime) -> list[dict]:
        indexed = {(row["day"], row["alert_type"]): row for row in rows}
        result = []
        day = start.date()
        while day <= end.date():
            day_key = day.isoformat()
            for alert_type in ("fall", "unknown_person"):
                result.append(
                    indexed.get(
                        (day_key, alert_type),
                        {"day": day_key, "alert_type": alert_type, "total": 0, "confirmed": 0, "false_alarms": 0},
                    )
                )
            day += timedelta(days=1)
        return result

    @staticmethod
    def _camera_distribution(connection, start: datetime, end: datetime) -> list[dict]:
        rows = connection.execute(
            """WITH latest_verdict AS (
                   SELECT a.id alert_id,
                          (SELECT aa.human_verdict FROM alert_actions aa
                           WHERE aa.alert_id=a.id AND aa.human_verdict IS NOT NULL
                           ORDER BY aa.created_at DESC,aa.id DESC LIMIT 1) verdict
                   FROM alerts a
               )
               SELECT c.id, c.name, c.location_label, count(DISTINCT a.id) alert_count,
                      count(DISTINCT CASE WHEN lv.verdict='false_positive' THEN a.id END) false_count,
                      count(DISTINCT CASE WHEN lv.verdict IS NOT NULL THEN a.id END) reviewed_count
               FROM cameras c LEFT JOIN events e ON e.camera_id=c.id
               LEFT JOIN alerts a ON a.event_id=e.id AND e.occurred_at>=? AND e.occurred_at<?
               LEFT JOIN latest_verdict lv ON lv.alert_id=a.id
               GROUP BY c.id ORDER BY alert_count DESC, c.name""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [
            {
                "id": row["id"], "name": row["name"], "location": row["location_label"],
                "alert_count": row["alert_count"],
                "false_alarm_rate": row["false_count"] / row["reviewed_count"] if row["reviewed_count"] else 0,
            }
            for row in rows
        ]

    @staticmethod
    def _false_alarm_reasons(connection, start: datetime, end: datetime) -> list[dict]:
        rows = connection.execute(
            """SELECT trim(aa.note) note, count(*) count FROM alert_actions aa
               JOIN alerts a ON a.id=aa.alert_id JOIN events e ON e.id=a.event_id
               WHERE aa.human_verdict='false_positive' AND aa.note IS NOT NULL AND trim(aa.note)<>''
                 AND e.occurred_at>=? AND e.occurred_at<? GROUP BY lower(trim(aa.note)) ORDER BY count DESC LIMIT 5""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _device_status(connection) -> list[dict]:
        rows = connection.execute(
            """SELECT c.id, c.name, c.location_label, c.operational_status, c.last_seen_at,
                      im.fps, im.latency_ms, im.measured_at inference_measured_at,
                      dm.ram_usage_mb, dm.ram_total_mb, dm.cpu_usage_percent, dm.ping_ms,
                      dm.disk_usage_percent, dm.measured_at device_measured_at
               FROM cameras c
               LEFT JOIN inference_metrics im ON im.id=(SELECT id FROM inference_metrics WHERE camera_id=c.id ORDER BY measured_at DESC LIMIT 1)
               LEFT JOIN device_metrics dm ON dm.id=(SELECT id FROM device_metrics WHERE camera_id=c.id ORDER BY measured_at DESC LIMIT 1)
               ORDER BY c.name"""
        ).fetchall()
        devices = [dict(row) for row in rows]
        hub = connection.execute(
            """SELECT ram_usage_mb, ram_total_mb, cpu_usage_percent, ping_ms,
                      disk_usage_percent, measured_at device_measured_at
               FROM device_metrics WHERE camera_id IS NULL ORDER BY measured_at DESC LIMIT 1"""
        ).fetchone()
        if hub:
            devices.insert(
                0,
                {
                    "id": "hub", "name": "Hub / Server", "location_label": "Thiết bị trung tâm",
                    "operational_status": "online", "last_seen_at": hub["device_measured_at"],
                    "fps": None, "latency_ms": None, "inference_measured_at": None,
                    **dict(hub),
                },
            )
        return devices

    @staticmethod
    def _performance_timeline(connection, start: datetime, end: datetime) -> list[dict]:
        rows = connection.execute(
            """SELECT im.measured_at, c.name camera_name, im.fps, im.latency_ms
               FROM inference_metrics im JOIN cameras c ON c.id=im.camera_id
               WHERE im.measured_at>=? AND im.measured_at<? ORDER BY im.measured_at""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _threshold_alerts(devices: list[dict]) -> list[dict]:
        alerts = []
        for device in devices:
            ram_percent = (
                device["ram_usage_mb"] / device["ram_total_mb"] * 100
                if device["ram_usage_mb"] is not None and device["ram_total_mb"]
                else None
            )
            reasons = []
            if ram_percent is not None and ram_percent > 90:
                reasons.append("RAM trên 90%")
            if device["cpu_usage_percent"] is not None and device["cpu_usage_percent"] > 90:
                reasons.append("CPU trên 90%")
            if device["fps"] is not None and device["fps"] < 10:
                reasons.append("FPS dưới 10")
            if reasons:
                alerts.append({"camera_id": device["id"], "camera_name": device["name"], "reasons": reasons})
        return alerts


statistics_service = StatisticsService()
