import asyncio
from dataclasses import dataclass
from pathlib import Path

from src.models.schemas import AlertReviewRequest, VisionEventAccepted, VisionEventRequest


class EventNotFoundError(Exception):
    pass


class EventService:
    """Baseline in-memory repository and application service.

    API và Vision pipeline chỉ làm việc qua service này. Có thể thay phần lưu RAM
    bằng SQLite mà không đổi contract của hai phía.
    """

    def __init__(self) -> None:
        self._alerts: list[dict] = []
        self._by_event_id: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    async def create(self, event: VisionEventRequest) -> VisionEventAccepted:
        async with self._lock:
            existing = self._by_event_id.get(event.event_id)
            if existing:
                return VisionEventAccepted(
                    id=existing["id"], event_id=event.event_id, duplicate=True, status=existing["status"]
                )

            snapshot_url = None
            if event.snapshot_path:
                snapshot_url = f"/snapshots/{Path(event.snapshot_path).name}"

            alert = {
                "id": len(self._alerts) + 1,
                "event_id": event.event_id,
                "timestamp": event.occurred_at.isoformat(),
                "event_type": event.event_type,
                "description": self._description(event),
                "camera_id": event.camera_id,
                "camera_location": event.camera_location,
                "confidence": event.confidence,
                "track_id": event.track_id,
                "identity_status": event.identity_status,
                "identity_name": event.identity_name,
                "immobile_seconds": event.immobile_seconds,
                "snapshot_url": snapshot_url,
                "status": "pending",
                "feedback": None,
                "review_note": None,
                "metadata": event.metadata,
            }
            self._alerts.append(alert)
            self._by_event_id[event.event_id] = alert
            return VisionEventAccepted(id=alert["id"], event_id=event.event_id, status=alert["status"])

    async def list_alerts(self) -> list[dict]:
        async with self._lock:
            return [dict(item) for item in reversed(self._alerts)]

    async def review(self, alert_id: int, review: AlertReviewRequest) -> dict:
        async with self._lock:
            alert = self._find(alert_id)
            alert["status"] = review.status
            alert["feedback"] = review.status
            alert["review_note"] = review.note
            return dict(alert)

    async def confirm_legacy(self, alert_id: int, feedback: str) -> None:
        async with self._lock:
            self._find(alert_id)["feedback"] = feedback

    async def clear(self) -> None:
        async with self._lock:
            self._alerts.clear()
            self._by_event_id.clear()

    def _find(self, alert_id: int) -> dict:
        for alert in self._alerts:
            if alert["id"] == alert_id:
                return alert
        raise EventNotFoundError(alert_id)

    @staticmethod
    def _description(event: VisionEventRequest) -> str:
        labels = {
            "FALL_SUSPECTED": "Phát hiện tư thế có khả năng té ngã",
            "FALL_CONFIRMED": "Phát hiện té ngã và bất động",
            "UNKNOWN_PERSON": "Phát hiện người chưa được nhận diện",
            "PERSON_RECOGNIZED": f"Đã nhận diện {event.identity_name or 'người thân'}",
            "INACTIVITY_DETECTED": "Không phát hiện hoạt động trong thời gian dài",
            "CAMERA_OFFLINE": "Camera mất kết nối",
            "CAMERA_ONLINE": "Camera đã kết nối lại",
        }
        return f"{labels[event.event_type]} tại {event.camera_location}."


@dataclass
class QueuedEvent:
    event: VisionEventRequest
    result: asyncio.Future[VisionEventAccepted]


class VisionEventSink:
    """Bounded, non-polling bridge for an in-process Vision pipeline."""

    def __init__(self, service: EventService, maxsize: int = 100) -> None:
        self._service = service
        self._maxsize = maxsize
        self._queue: asyncio.Queue[QueuedEvent] | None = None

    def start(self) -> None:
        """Bind a fresh queue to the application's current event loop."""
        self._queue = asyncio.Queue(maxsize=self._maxsize)

    async def publish(self, event: VisionEventRequest) -> VisionEventAccepted:
        if self._queue is None:
            raise RuntimeError("VisionEventSink has not been started")
        loop = asyncio.get_running_loop()
        result: asyncio.Future[VisionEventAccepted] = loop.create_future()
        await self._queue.put(QueuedEvent(event, result))
        return await result

    async def consume(self) -> None:
        if self._queue is None:
            raise RuntimeError("VisionEventSink has not been started")
        while True:
            queued = await self._queue.get()
            try:
                accepted = await self._service.create(queued.event)
                if not queued.result.done():
                    queued.result.set_result(accepted)
            except Exception as exc:
                if not queued.result.done():
                    queued.result.set_exception(exc)
            finally:
                self._queue.task_done()


event_service = EventService()
vision_event_sink = VisionEventSink(event_service)
