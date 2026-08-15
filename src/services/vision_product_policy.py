import json
import threading
from uuid import uuid4

from src.database import database_connection
from src.models.vision import VisionEvent, VisionResult


def unknown_identity_scores(value: object) -> tuple[float, float]:
    """Return clamped cosine similarity and its UI mismatch score."""
    similarity = max(0.0, min(1.0, float(value)))
    return similarity, 1.0 - similarity


class VisionProductPolicy:
    """Turns structured AI output into rate-limited product events."""

    def __init__(self, unknown_cooldown_seconds: float = 30.0, clock=None):
        self._unknown_cooldown_seconds = unknown_cooldown_seconds
        self._clock = clock
        self._lock = threading.RLock()
        self._last_unknown: dict[tuple[str, int, int], float] = {}

    def apply(self, result: VisionResult) -> VisionResult:
        unknown_candidates = [
            detection
            for detection in result.detections
            if detection.track_id is not None
            and detection.metadata.get("identity_state") == "LOCKED_UNKNOWN"
            and detection.metadata.get("identity_face_detected", False)
        ]
        if not result.events and not unknown_candidates:
            return result
        general = self._general_settings()
        fall_threshold = float(general.get("fall_threshold", 72)) / 100.0
        result.events[:] = [
            event
            for event in result.events
            if event.type != "fall_confirmed" or event.confidence >= fall_threshold
        ]

        stranger_threshold = float(general.get("stranger_threshold", 78)) / 100.0
        now = (
            self._clock()
            if self._clock is not None
            else float(result.metadata.get("observation_time", result.captured_at))
        )
        for detection in unknown_candidates:
            metadata = detection.metadata
            track_id = detection.track_id
            assert track_id is not None
            similarity, mismatch_score = unknown_identity_scores(
                metadata.get("identity_similarity", 0.0)
            )
            if mismatch_score < stranger_threshold:
                continue
            key = (result.camera_id, int(result.metadata.get("source_epoch", 0)), track_id)
            with self._lock:
                last_emitted = self._last_unknown.get(key)
                if last_emitted is not None and now - last_emitted < self._unknown_cooldown_seconds:
                    continue
                self._last_unknown[key] = now
            event_id = str(uuid4())
            result.events.append(
                VisionEvent(
                    type="unknown_person",
                    confidence=mismatch_score,
                    metadata={
                        "event_id": f"{event_id}:unknown_person",
                        "track_id": track_id,
                        "identity_status": "UNKNOWN",
                        "identity_similarity": similarity,
                        "stranger_confidence": mismatch_score,
                    },
                )
            )
        return result

    def clear_camera(self, camera_id: str) -> None:
        """Discard feature-specific cooldown state across an OFF/ON boundary."""
        with self._lock:
            for key in [key for key in self._last_unknown if key[0] == camera_id]:
                self._last_unknown.pop(key, None)

    @staticmethod
    def _general_settings() -> dict:
        with database_connection() as connection:
            row = connection.execute(
                "SELECT value_json FROM system_settings WHERE setting_key = 'general'"
            ).fetchone()
        return json.loads(row["value_json"]) if row is not None else {}
