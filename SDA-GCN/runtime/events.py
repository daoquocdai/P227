"""Optional asynchronous event delivery for standalone Vision runtime."""

from __future__ import annotations

import queue
import threading
import time
from typing import Optional
import warnings

import requests


class EventSender:
    """Deliver events off the inference thread through a bounded queue."""

    def __init__(self, backend_url: Optional[str] = None, queue_size: int = 32):
        self.backend_url = backend_url
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._last_warning_at = 0.0
        self._thread = None
        if backend_url:
            self._thread = threading.Thread(target=self._run, name="vision-event-sender", daemon=True)
            self._thread.start()

    @property
    def enabled(self) -> bool:
        return self.backend_url is not None

    def enqueue(self, payload: dict) -> None:
        if not self.enabled:
            return
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            self._warn("Event queue is full; dropping event.")

    def _warn(self, message: str) -> None:
        now = time.monotonic()
        if now - self._last_warning_at >= 30.0:
            warnings.warn(message, RuntimeWarning, stacklevel=2)
            self._last_warning_at = now

    def _run(self) -> None:
        session = requests.Session()
        while not self._stop.is_set():
            try:
                payload = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                session.post(self.backend_url, json=payload, timeout=(0.5, 1.0)).raise_for_status()
            except requests.RequestException as exc:
                self._warn(f"Event backend unavailable: {exc}")
            finally:
                self._queue.task_done()
        session.close()

    def close(self, timeout: float = 1.5) -> None:
        if self._thread is None:
            return
        self._stop.set()
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break
        self._thread.join(timeout=timeout)
