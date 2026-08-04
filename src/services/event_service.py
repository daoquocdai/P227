import asyncio
from dataclasses import dataclass

from src.models.schemas import AlertReviewRequest, VisionEventAccepted, VisionEventRequest
from src.services.alert_broadcaster import alert_broadcaster
from src.services.sqlite_event_repository import EventNotFoundError, SQLiteEventRepository


class EventService:
    """Application service shared by Vision ingestion and dashboard APIs."""

    def __init__(self, repository: SQLiteEventRepository | None = None) -> None:
        self._repository = repository or SQLiteEventRepository()
        self._lock = asyncio.Lock()

    async def create(self, event: VisionEventRequest) -> VisionEventAccepted:
        async with self._lock:
            result = self._repository.create(event, self._description(event))
            alert = self._repository.get_alert(result.id) if result.status == "pending" and not result.duplicate else None
        if alert:
            await alert_broadcaster.publish({"type": "alert_created", "alert": alert})
        return result

    async def list_alerts(self) -> list[dict]:
        async with self._lock:
            return self._repository.list_alerts()

    async def get_alert(self, alert_id: str) -> dict:
        async with self._lock:
            return self._repository.get_alert(alert_id)

    async def mark_read(self, alert_id: str) -> dict:
        async with self._lock:
            alert = self._repository.mark_read(alert_id)
        await alert_broadcaster.publish({"type": "alert_updated", "alert": alert})
        return alert

    async def review(self, alert_id: str, review: AlertReviewRequest) -> dict:
        async with self._lock:
            alert = self._repository.review(alert_id, review)
        await alert_broadcaster.publish({"type": "alert_updated", "alert": alert})
        return alert

    async def confirm_legacy(self, alert_id: str, feedback: str) -> None:
        async with self._lock:
            self._repository.confirm_legacy(alert_id, feedback)

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

__all__ = ["EventNotFoundError", "EventService", "event_service", "vision_event_sink"]
