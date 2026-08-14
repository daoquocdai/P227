import asyncio
from dataclasses import dataclass

from src.models.schemas import (
    AlertReviewRequest,
    VisionEventAccepted,
    VisionEventRequest,
)
from src.services.alert_broadcaster import alert_broadcaster
from src.services.camera_service import camera_service
from src.services.event_presentation import event_description
from src.services.sqlite_event_repository import (
    EventNotFoundError,
    SQLiteEventRepository,
)


class EventService:
    """Application service shared by Vision ingestion and dashboard APIs."""

    def __init__(self, repository: SQLiteEventRepository | None = None) -> None:
        self._repository = repository or SQLiteEventRepository()
        self._lock = asyncio.Lock()

    async def create(self, event: VisionEventRequest) -> VisionEventAccepted:
        async with self._lock:
            if (
                event.event_type == "UNKNOWN_PERSON"
                and camera_service.identity_enabled_state(event.camera_id) is False
            ):
                return VisionEventAccepted(
                    id=event.event_id,
                    event_id=event.event_id,
                    accepted=False,
                    status="resolved",
                )
            result = self._repository.create(event, self._description(event))
            alert = (
                self._repository.get_alert(result.id) if result.status == "pending" and not result.duplicate else None
            )
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
        return event_description(event.event_type, event.camera_location, event.identity_name)


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

    @property
    def maxsize(self) -> int:
        return self._maxsize

    def publish_nowait(self, event: VisionEventRequest) -> asyncio.Future[VisionEventAccepted]:
        """Enqueue from the owning event-loop thread without waiting for space."""
        if self._queue is None:
            raise RuntimeError("VisionEventSink has not been started")
        loop = asyncio.get_running_loop()
        result: asyncio.Future[VisionEventAccepted] = loop.create_future()
        self._queue.put_nowait(QueuedEvent(event, result))
        return result

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
            except asyncio.CancelledError:
                if not queued.result.done():
                    queued.result.set_exception(RuntimeError("VisionEventSink consumer stopped"))
                raise
            except Exception as exc:  # noqa: BLE001 - delivery must isolate repository failures
                if not queued.result.done():
                    queued.result.set_exception(exc)
            finally:
                self._queue.task_done()

    def stop(self) -> None:
        queue = self._queue
        self._queue = None
        if queue is None:
            return
        while not queue.empty():
            queued = queue.get_nowait()
            if not queued.result.done():
                queued.result.set_exception(RuntimeError("VisionEventSink stopped before delivery"))
            queue.task_done()


event_service = EventService()
vision_event_sink = VisionEventSink(event_service)

__all__ = ["EventNotFoundError", "EventService", "event_service", "vision_event_sink"]
