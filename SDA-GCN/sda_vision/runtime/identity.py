"""Process-isolated InsightFace recognition and identity association state."""

from __future__ import annotations

import contextlib
import io
import multiprocessing as mp
import os
import queue
import time
import warnings
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

import cv2
import numpy as np

from ..contracts import IdentityGallerySnapshot
from .gallery import build_gallery, recognition_fingerprint


class IdentityState(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    LOCKED_KNOWN = "LOCKED_KNOWN"
    LOCKED_UNKNOWN = "LOCKED_UNKNOWN"


@dataclass(frozen=True)
class IdentityResult:
    state: IdentityState = IdentityState.UNVERIFIED
    name: str | None = None
    confidence: float = 0.0
    timestamp: float = 0.0
    bbox: tuple[int, int, int, int] | None = None
    inference_ms: float | None = None
    source_time_s: float | None = None
    frame_sequence: int | None = None
    face_bbox: tuple[int, int, int, int] | None = None
    face_bbox_frame_sequence: int | None = None
    inference_started_monotonic_s: float | None = None
    inference_finished_monotonic_s: float | None = None
    inference_started_wall_time_s: float | None = None
    inference_finished_wall_time_s: float | None = None
    person_id: str | None = None
    gallery_version: int | str | None = None
    face_found: bool | None = None
    association_id: int | None = None


def _replace_latest(target_queue, item):
    try:
        target_queue.put_nowait(item)
        return False
    except queue.Full:
        try:
            target_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            target_queue.put_nowait(item)
        except queue.Full:
            return True
        return True


def _similarity(first, second):
    denominator = np.linalg.norm(first) * np.linalg.norm(second)
    return float(np.dot(first, second) / denominator) if denominator else 0.0


def validate_process_priority(value):
    normalized = str(value).strip().lower()
    if normalized not in {"normal", "below_normal"}:
        raise ValueError("identity_process_priority must be 'normal' or 'below_normal'")
    return normalized


def validate_cpu_affinity(value, allowed=None):
    if value is None:
        return None
    normalized = tuple(dict.fromkeys(int(cpu) for cpu in value))
    if not normalized or any(cpu < 0 for cpu in normalized):
        raise ValueError("identity_cpu_affinity must contain non-negative CPU IDs")
    if allowed is not None:
        invalid = sorted(set(normalized) - set(allowed))
        if invalid:
            raise ValueError(f"identity_cpu_affinity contains disallowed CPU IDs: {invalid}")
    return normalized


def _apply_process_isolation(providers, priority, affinity):
    """Apply best-effort child-only isolation and return truthful diagnostics."""
    priority = validate_process_priority(priority)
    affinity = validate_cpu_affinity(affinity)
    status = {
        "configured_priority": priority,
        "effective_priority": "normal",
        "configured_affinity": affinity,
        "effective_affinity": None,
        "isolation_applied": False,
        "isolation_reason": None,
    }
    if not providers or providers[0] != "CPUExecutionProvider":
        status["isolation_reason"] = "CPU isolation skipped for non-CPU primary provider"
        return status
    try:
        import psutil

        process = psutil.Process()
        allowed = process.cpu_affinity() if hasattr(process, "cpu_affinity") else None
        affinity = validate_cpu_affinity(affinity, allowed)
        if affinity is not None:
            if not hasattr(process, "cpu_affinity"):
                status["isolation_reason"] = "CPU affinity is unsupported on this platform"
            else:
                process.cpu_affinity(list(affinity))
                status["effective_affinity"] = tuple(process.cpu_affinity())
                status["isolation_applied"] = True
        elif allowed is not None:
            status["effective_affinity"] = tuple(allowed)

        if priority == "below_normal":
            if os.name == "nt":
                process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            else:
                process.nice(10)
            status["effective_priority"] = "below_normal"
            status["isolation_applied"] = True
    except (ImportError, OSError, ValueError) as exc:
        status["isolation_reason"] = str(exc)
    except Exception as exc:  # psutil platform-specific AccessDenied/NoSuchProcess
        status["isolation_reason"] = str(exc)
    return status


def _identity_process(
    input_queue,
    result_queue,
    status_queue,
    stop_event,
    ready_event,
    providers,
    data_dir,
    cache_path,
    det_size,
    detection_threshold,
    threshold,
    rebuild_cache,
    debug,
    identity_debug,
    process_priority,
    cpu_affinity,
    gallery_mode,
    initial_gallery,
    gallery_queue,
):
    isolation_status = _apply_process_isolation(providers, process_priority, cpu_affinity)
    from insightface.app import FaceAnalysis

    process_started = time.perf_counter()
    captured_stdout, captured_stderr = io.StringIO(), io.StringIO()
    output_context = contextlib.nullcontext() if debug else contextlib.ExitStack()
    if not debug:
        output_context.enter_context(contextlib.redirect_stdout(captured_stdout))
        output_context.enter_context(contextlib.redirect_stderr(captured_stderr))
    try:
        with output_context, warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=r"SymbolDatabase.GetPrototype\(\) is deprecated")
            model_started = time.perf_counter()
            app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"], providers=providers)
            app.prepare(
                ctx_id=0 if providers[0] != "CPUExecutionProvider" else -1,
                det_thresh=detection_threshold,
                det_size=(det_size, det_size),
            )
            model_ms = (time.perf_counter() - model_started) * 1000.0
    except Exception as exc:
        _replace_latest(
            status_queue,
            {
                "startup_error": str(exc),
                "requested_providers": list(providers),
                "effective_providers": [],
                "execution": isolation_status,
            },
        )
        ready_event.set()
        return

    effective_providers = []
    for model in getattr(app, "models", {}).values():
        session = getattr(model, "session", None)
        if session is not None and hasattr(session, "get_providers"):
            effective_providers.extend(session.get_providers())
    effective_providers = list(dict.fromkeys(effective_providers))

    root = Path(data_dir)

    def extract(path):
        image = cv2.imread(str(path))
        if image is None:
            return None, "cannot read file"
        faces = app.get(image)
        if not faces:
            return None, "no face detected"
        if len(faces) != 1:
            return None, f"multiple faces detected ({len(faces)})"
        return faces[0].embedding, None

    if gallery_mode == "filesystem":
        model_root = Path.home() / ".insightface" / "models" / "buffalo_l"
        known, gallery_stats = build_gallery(
            root,
            Path(cache_path),
            recognition_fingerprint(model_root),
            extract,
            rebuild=rebuild_cache,
            info=lambda message: print(message, flush=True),
            warning=lambda message: print(message, flush=True),
            progress=debug or rebuild_cache,
        )
        gallery_version = "filesystem"
        gallery_entries = tuple((None, name, embedding) for name, embedding in known.items())
    else:
        snapshot = initial_gallery or IdentityGallerySnapshot(0)
        gallery_version = snapshot.version
        gallery_entries = tuple((entry.person_id, entry.name, entry.embedding) for entry in snapshot.entries)
        gallery_stats = type(
            "SuppliedGalleryStats",
            (),
            {
                "elapsed_ms": 0.0,
                "persons": len({entry[0] for entry in gallery_entries}),
                "images": len(gallery_entries),
                "cached": len(gallery_entries),
                "recomputed": 0,
                "skipped": 0,
            },
        )()

    ready_payload = {
        "model_ms": model_ms,
        "gallery_ms": gallery_stats.elapsed_ms,
        "ready_ms": (time.perf_counter() - process_started) * 1000.0,
        "persons": gallery_stats.persons,
        "images": gallery_stats.images,
        "cached": gallery_stats.cached,
        "recomputed": gallery_stats.recomputed,
        "skipped": gallery_stats.skipped,
        "execution": isolation_status,
        "requested_providers": list(providers),
        "effective_providers": effective_providers,
    }
    _replace_latest(status_queue, ready_payload)

    ready_event.set()

    while not stop_event.is_set():
        latest_gallery = None
        while True:
            try:
                latest_gallery = gallery_queue.get_nowait()
            except queue.Empty:
                break
        if latest_gallery is not None:
            applied_at = time.perf_counter()
            gallery_version = latest_gallery.version
            gallery_entries = tuple((entry.person_id, entry.name, entry.embedding) for entry in latest_gallery.entries)
            _replace_latest(
                status_queue,
                {
                    "gallery_version": gallery_version,
                    "gallery_entries": len(gallery_entries),
                    "gallery_apply_ms": (time.perf_counter() - applied_at) * 1000.0,
                },
            )
        try:
            job = input_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        started = time.perf_counter()
        started_wall = time.time()
        faces = app.get(job["crop"])
        person_id, name, score, main_face = None, None, 0.0, None
        inference_gallery_version = gallery_version
        if faces:
            main_face = max(faces, key=lambda face: (face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1]))
            for candidate_person_id, candidate_name, embedding in gallery_entries:
                candidate_score = _similarity(embedding, main_face.embedding)
                if candidate_score > score:
                    person_id, name, score = candidate_person_id, candidate_name, candidate_score
        finished = time.perf_counter()
        finished_wall = time.time()
        payload = {
            "known": bool(name is not None and score > threshold),
            "face_found": bool(faces),
            "person_id": person_id,
            "name": name,
            "confidence": score,
            "gallery_version": inference_gallery_version,
            "bbox": job["bbox"],
            "timestamp": time.monotonic(),
            "inference_ms": (finished - started) * 1000.0,
            "inference_started_monotonic_s": started,
            "inference_finished_monotonic_s": finished,
            "inference_started_wall_time_s": started_wall,
            "inference_finished_wall_time_s": finished_wall,
            "source_time_s": job.get("source_time_s"),
            "frame_sequence": job.get("frame_sequence"),
            "association_id": job.get("association_id"),
            "face_bbox": (tuple(int(round(value)) for value in main_face.bbox) if main_face is not None else None),
        }
        if identity_debug:
            print("\n[Identity Match]")
            print(f"Faces       : {len(faces)}")
            print(f"Best        : {name or 'none'}")
            print(f"Similarity  : {score:.3f}")
            print(f"Threshold   : {threshold:.3f}")
            print(f"Inference   : {payload['inference_ms']:.0f} ms")
        _replace_latest(result_queue, payload)


class IdentityStage:
    """Non-blocking facade; real tracking can replace bbox association later."""

    def __init__(
        self,
        providers,
        data_dir,
        cache_path,
        det_size=416,
        detection_threshold=0.4,
        interval=0.3,
        unknown_retry=1.0,
        locked_unknown_retry=3.0,
        max_unknown_attempts=3,
        absent_timeout=1.5,
        threshold=0.45,
        rebuild_cache=False,
        debug=False,
        identity_debug=False,
        process_priority="normal",
        cpu_affinity=None,
        gallery_mode="filesystem",
        gallery_snapshot=None,
    ):
        if gallery_mode not in {"filesystem", "supplied"}:
            raise ValueError("identity gallery mode must be 'filesystem' or 'supplied'")
        if gallery_mode == "supplied" and gallery_snapshot is None:
            gallery_snapshot = IdentityGallerySnapshot(0)
        process_priority = validate_process_priority(process_priority)
        if cpu_affinity is not None:
            try:
                import psutil

                allowed_affinity = psutil.Process().cpu_affinity()
            except (ImportError, OSError, AttributeError):
                allowed_affinity = None
            except Exception:  # psutil platform-specific access errors
                allowed_affinity = None
            cpu_affinity = validate_cpu_affinity(cpu_affinity, allowed_affinity)
        context = mp.get_context("spawn")
        self._inputs = context.Queue(maxsize=1)
        self._results = context.Queue(maxsize=1)
        self._status = context.Queue(maxsize=1)
        self._gallery_updates = context.Queue(maxsize=1)
        self._stop = context.Event()
        self._ready = context.Event()
        self._process = context.Process(
            target=_identity_process,
            args=(
                self._inputs,
                self._results,
                self._status,
                self._stop,
                self._ready,
                providers,
                str(data_dir),
                str(cache_path),
                det_size,
                detection_threshold,
                threshold,
                rebuild_cache,
                debug,
                identity_debug,
                process_priority,
                cpu_affinity,
                gallery_mode,
                gallery_snapshot,
                self._gallery_updates,
            ),
            name="vision-identity",
            daemon=True,
        )
        self.interval = interval
        self.detection_threshold = detection_threshold
        self.recognition_threshold = threshold
        self.unknown_retry = unknown_retry
        self.locked_unknown_retry = locked_unknown_retry
        self.max_unknown_attempts = max_unknown_attempts
        self.absent_timeout = absent_timeout
        self.result = IdentityResult()
        self.failed_attempts = 0
        self.last_attempt_at = 0.0
        self.last_present_at = 0.0
        self.association_bbox = None
        self.association_id = None
        self.association_generation = 0
        self.frames_submitted = 0
        self.frames_processed = 0
        self.frames_dropped = 0
        self.started_at = time.monotonic()
        self.gallery_status = None
        self.process_priority = process_priority
        self.cpu_affinity = cpu_affinity
        self.gallery_mode = gallery_mode
        self.gallery_snapshot = gallery_snapshot
        self.gallery_version = gallery_snapshot.version if gallery_snapshot is not None else "filesystem"

    def start(self):
        self._process.start()

    @staticmethod
    def _iou(first, second):
        if first is None or second is None:
            return 0.0
        ax1, ay1, ax2, ay2 = first
        bx1, by1, bx2, by2 = second
        intersection = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
        union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection
        return intersection / union if union else 0.0

    def update_presence(self, bbox, now=None):
        now = now if now is not None else time.monotonic()
        if bbox is not None:
            if self.association_bbox is not None and self._iou(self.association_bbox, bbox) < 0.15:
                self.reset()
            if getattr(self, "association_id", None) is None:
                self.association_generation = getattr(self, "association_generation", 0) + 1
                self.association_id = self.association_generation
            self.association_bbox = bbox
            self.last_present_at = now
        elif self.last_present_at and now - self.last_present_at >= self.absent_timeout:
            self.reset()

    def reset(self, *, preserve_association=False):
        association_id = getattr(self, "association_id", None) if preserve_association else None
        self.result = IdentityResult(
            gallery_version=getattr(self, "gallery_version", None), association_id=association_id
        )
        self.failed_attempts = 0
        self.last_attempt_at = 0.0
        if not preserve_association:
            self.association_bbox = None
            self.association_id = None

    def _due(self, now):
        state = self.result.state
        if state == IdentityState.LOCKED_KNOWN:
            return False
        cooldown = self.interval
        if self.result.face_found is False:
            cooldown = self.interval
        elif state == IdentityState.UNKNOWN:
            cooldown = self.unknown_retry
        elif state == IdentityState.LOCKED_UNKNOWN:
            cooldown = self.locked_unknown_retry
        return now - self.last_attempt_at >= cooldown

    def submit(self, crop, bbox, now=None, source_time_s=None, frame_sequence=None):
        # Presence/cooldown semantics follow the source timeline. Runtime
        # throughput metrics continue to use monotonic/perf_counter clocks.
        now = source_time_s if source_time_s is not None else (now if now is not None else time.monotonic())
        self.poll()
        self.update_presence(bbox, now)
        if not self.ready:
            return False
        if not self._due(now):
            return False
        self.last_attempt_at = now
        self.frames_submitted += 1
        if _replace_latest(
            self._inputs,
            {
                "crop": crop,
                "bbox": bbox,
                "source_time_s": source_time_s,
                "frame_sequence": frame_sequence,
                "gallery_version": self.gallery_version,
                "association_id": self.association_id,
            },
        ):
            self.frames_dropped += 1
        return True

    def poll(self):
        self.poll_status()
        latest = None
        while True:
            try:
                latest = self._results.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            return self.result
        gallery_version = getattr(self, "gallery_version", None)
        if latest.get("gallery_version") != gallery_version:
            return self.result
        if latest.get("association_id") != getattr(self, "association_id", None):
            return self.result
        self.frames_processed += 1
        if self.association_bbox is not None and self._iou(self.association_bbox, latest["bbox"]) < 0.15:
            # Result belongs to a superseded presence association; never lock it
            # onto the person currently visible.
            return self.result
        if latest["known"]:
            # KNOWN is an explicit successful transition; locking is immediate.
            common = dict(
                name=latest["name"],
                confidence=latest["confidence"],
                timestamp=latest["timestamp"],
                bbox=latest["bbox"],
                inference_ms=latest["inference_ms"],
                source_time_s=latest.get("source_time_s"),
                frame_sequence=latest.get("frame_sequence"),
                face_bbox=latest.get("face_bbox"),
                face_bbox_frame_sequence=latest.get("frame_sequence"),
                inference_started_monotonic_s=latest.get("inference_started_monotonic_s"),
                inference_finished_monotonic_s=latest.get("inference_finished_monotonic_s"),
                inference_started_wall_time_s=latest.get("inference_started_wall_time_s"),
                inference_finished_wall_time_s=latest.get("inference_finished_wall_time_s"),
                person_id=latest.get("person_id"),
                gallery_version=gallery_version,
                face_found=True,
                association_id=self.association_id,
            )
            self.result = IdentityResult(IdentityState.KNOWN, **common)
            self.result = IdentityResult(IdentityState.LOCKED_KNOWN, **common)
            self.failed_attempts = 0
        elif latest.get("face_found"):
            self.failed_attempts += 1
            state = (
                IdentityState.LOCKED_UNKNOWN
                if self.failed_attempts >= self.max_unknown_attempts
                else IdentityState.UNKNOWN
            )
            self.result = IdentityResult(
                state=state,
                confidence=latest["confidence"],
                timestamp=latest["timestamp"],
                bbox=latest["bbox"],
                inference_ms=latest["inference_ms"],
                source_time_s=latest.get("source_time_s"),
                frame_sequence=latest.get("frame_sequence"),
                face_bbox=latest.get("face_bbox"),
                face_bbox_frame_sequence=latest.get("frame_sequence"),
                inference_started_monotonic_s=latest.get("inference_started_monotonic_s"),
                inference_finished_monotonic_s=latest.get("inference_finished_monotonic_s"),
                inference_started_wall_time_s=latest.get("inference_started_wall_time_s"),
                inference_finished_wall_time_s=latest.get("inference_finished_wall_time_s"),
                gallery_version=gallery_version,
                face_found=True,
                association_id=getattr(self, "association_id", None),
            )
        else:
            # No usable face is inconclusive: retain the current state and
            # attempt count, but expose that this inference did not verify a face.
            self.result = replace(
                self.result,
                timestamp=latest["timestamp"],
                bbox=latest["bbox"],
                inference_ms=latest["inference_ms"],
                face_found=False,
                face_bbox=None,
                face_bbox_frame_sequence=latest.get("frame_sequence"),
                association_id=self.association_id,
            )
        return self.result

    def update_gallery(self, snapshot):
        if self.gallery_mode != "supplied":
            raise RuntimeError("Filesystem Identity gallery cannot accept supplied updates")
        self.gallery_snapshot = snapshot
        self.gallery_version = snapshot.version
        self.reset(preserve_association=True)
        _replace_latest(self._gallery_updates, snapshot)

    def poll_status(self):
        latest = None
        while True:
            try:
                latest = self._status.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            if self.gallery_status is None:
                self.gallery_status = latest
            else:
                self.gallery_status.update(latest)
        return self.gallery_status

    @property
    def effective_hz(self):
        elapsed = time.monotonic() - self.started_at
        return self.frames_processed / elapsed if elapsed else 0.0

    @property
    def ready(self):
        return self._ready.is_set()

    def stop(self, timeout=3.0):
        self._stop.set()
        self._process.join(timeout)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=1.0)
        self._inputs.close()
        self._results.close()
        self._status.close()
        self._gallery_updates.close()
