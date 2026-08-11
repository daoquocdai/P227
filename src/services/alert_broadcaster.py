import asyncio
from collections.abc import AsyncIterator


class AlertBroadcaster:
    """In-process fan-out for a single Local Hub FastAPI worker."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict]] = set()

    async def publish(self, message: dict) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(message)

    async def subscribe(self) -> AsyncIterator[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=20)
                except TimeoutError:
                    yield {"type": "heartbeat"}
        finally:
            self._subscribers.discard(queue)


alert_broadcaster = AlertBroadcaster()
