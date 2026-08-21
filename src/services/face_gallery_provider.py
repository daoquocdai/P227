"""SQLite source-of-truth adapter for integrated SDA Identity galleries."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import numpy as np

from src.database import database_connection

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AppFaceGalleryEntry:
    person_id: str
    name: str
    embedding: np.ndarray


@dataclass(frozen=True, slots=True)
class AppFaceGallerySnapshot:
    revision: int | str
    entries: tuple[AppFaceGalleryEntry, ...] = ()


class SqliteFaceGalleryProvider:
    def load(self, version: int | str) -> tuple[AppFaceGallerySnapshot, dict]:
        started = time.perf_counter()
        entries = []
        skipped = 0
        with database_connection() as connection:
            rows = connection.execute(
                """SELECT fp.person_id, p.display_name, fp.embedding,
                          fp.embedding_dimension
                   FROM face_profiles fp JOIN persons p ON p.id = fp.person_id
                   WHERE fp.is_active = 1 AND p.is_active = 1
                   ORDER BY p.display_name, fp.created_at""").fetchall()
        for row in rows:
            raw = row["embedding"]
            try:
                dimension = int(row["embedding_dimension"])
            except (TypeError, ValueError):
                skipped += 1
                continue
            if raw is None or dimension <= 0:
                skipped += 1
                continue
            if len(raw) != dimension * np.dtype(np.float32).itemsize:
                skipped += 1
                continue
            embedding = np.frombuffer(raw, dtype=np.float32)
            if embedding.size != dimension or not np.isfinite(embedding).all():
                skipped += 1
                continue
            entries.append(AppFaceGalleryEntry(
                row["person_id"], row["display_name"], embedding.copy()))
        snapshot = AppFaceGallerySnapshot(version, tuple(entries))
        if skipped:
            logger.warning("Skipped %d invalid SQLite Identity embedding row(s)", skipped)
        return snapshot, {
            "entries": len(entries), "skipped": skipped,
            "load_ms": (time.perf_counter() - started) * 1000.0,
        }


class FaceGalleryCoordinator:
    def __init__(self, provider=None):
        self.provider = provider or SqliteFaceGalleryProvider()
        self._lock = threading.RLock()
        self._publisher = None
        self._revision = 0
        self.last_error = None
        self.last_metrics = None
        self._refresh_lock = threading.Lock()

    @property
    def revision(self):
        with self._lock:
            return self._revision

    def set_publisher(self, publisher):
        with self._lock:
            self._publisher = publisher

    def clear_publisher(self, publisher):
        with self._lock:
            if self._publisher is publisher:
                self._publisher = None

    def refresh(self):
        with self._refresh_lock:
            with self._lock:
                next_revision = self._revision + 1
            snapshot, metrics = self.provider.load(next_revision)
            with self._lock:
                self._revision = next_revision
                self.last_error = None
                self.last_metrics = metrics
                publisher = self._publisher
        if publisher is not None:
            publisher(snapshot)
        return snapshot

    def refresh_after_commit(self):
        try:
            return self.refresh()
        except Exception as exc:
            with self._lock:
                self.last_error = str(exc)
            logger.exception("SQLite Identity gallery refresh failed; Fall remains active")
            return None


face_gallery_coordinator = FaceGalleryCoordinator()
