"""Process-isolated InsightFace recognition and identity association state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import multiprocessing as mp
from pathlib import Path
import queue
import time
import contextlib
import io
import os
import warnings

import cv2
import numpy as np

from .gallery import build_gallery, recognition_fingerprint


class IdentityState(str, Enum):
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


def _identity_process(input_queue, result_queue, status_queue, stop_event, ready_event,
                      providers, data_dir, cache_path, det_size, threshold,
                      rebuild_cache, debug, identity_debug):
    from insightface.app import FaceAnalysis

    process_started = time.perf_counter()
    captured_stdout, captured_stderr = io.StringIO(), io.StringIO()
    output_context = contextlib.nullcontext() if debug else contextlib.ExitStack()
    if not debug:
        output_context.enter_context(contextlib.redirect_stdout(captured_stdout))
        output_context.enter_context(contextlib.redirect_stderr(captured_stderr))
    with output_context, warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="SymbolDatabase.GetPrototype\(\) is deprecated")
        model_started = time.perf_counter()
        app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"], providers=providers)
        app.prepare(ctx_id=0 if providers[0] != "CPUExecutionProvider" else -1, det_size=(det_size, det_size))
        model_ms = (time.perf_counter() - model_started) * 1000.0

    root = Path(data_dir)
    model_root = Path.home() / ".insightface" / "models" / "buffalo_l"
    fingerprint = recognition_fingerprint(model_root)

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

    known, gallery_stats = build_gallery(
        root, Path(cache_path), fingerprint, extract, rebuild=rebuild_cache,
        info=lambda message: print(message, flush=True),
        warning=lambda message: print(message, flush=True),
        progress=debug or rebuild_cache,
    )

    ready_payload = {
        "model_ms": model_ms, "gallery_ms": gallery_stats.elapsed_ms,
        "ready_ms": (time.perf_counter() - process_started) * 1000.0,
        "persons": gallery_stats.persons, "images": gallery_stats.images,
        "cached": gallery_stats.cached, "recomputed": gallery_stats.recomputed,
        "skipped": gallery_stats.skipped,
    }
    _replace_latest(status_queue, ready_payload)

    ready_event.set()

    while not stop_event.is_set():
        try:
            job = input_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        started = time.perf_counter()
        faces = app.get(job["crop"])
        name, score = None, 0.0
        if faces:
            main_face = max(faces, key=lambda face: (face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1]))
            for candidate, embedding in known.items():
                candidate_score = _similarity(embedding, main_face.embedding)
                if candidate_score > score:
                    name, score = candidate, candidate_score
        payload = {
            "known": bool(name is not None and score > threshold),
            "face_found": bool(faces), "name": name, "confidence": score,
            "bbox": job["bbox"], "timestamp": time.monotonic(),
            "inference_ms": (time.perf_counter() - started) * 1000.0,
            "source_time_s": job.get("source_time_s"),
            "frame_sequence": job.get("frame_sequence"),
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

    def __init__(self, providers, data_dir, cache_path, det_size=416, interval=0.5,
                 unknown_retry=1.0, locked_unknown_retry=15.0,
                 max_unknown_attempts=3, absent_timeout=1.5, threshold=0.45,
                 rebuild_cache=False, debug=False, identity_debug=False):
        context = mp.get_context("spawn")
        self._inputs = context.Queue(maxsize=1)
        self._results = context.Queue(maxsize=1)
        self._status = context.Queue(maxsize=1)
        self._stop = context.Event()
        self._ready = context.Event()
        self._process = context.Process(
            target=_identity_process,
            args=(self._inputs, self._results, self._status, self._stop, self._ready,
                  providers, str(data_dir), str(cache_path), det_size, threshold,
                  rebuild_cache, debug, identity_debug),
            name="vision-identity", daemon=True,
        )
        self.interval = interval
        self.unknown_retry = unknown_retry
        self.locked_unknown_retry = locked_unknown_retry
        self.max_unknown_attempts = max_unknown_attempts
        self.absent_timeout = absent_timeout
        self.result = IdentityResult()
        self.failed_attempts = 0
        self.last_attempt_at = 0.0
        self.last_present_at = 0.0
        self.association_bbox = None
        self.frames_submitted = 0
        self.frames_processed = 0
        self.frames_dropped = 0
        self.started_at = time.monotonic()
        self.gallery_status = None

    def start(self):
        self._process.start()

    @staticmethod
    def _iou(first, second):
        if first is None or second is None:
            return 0.0
        ax1, ay1, ax2, ay2 = first
        bx1, by1, bx2, by2 = second
        intersection = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
        union = (ax2-ax1)*(ay2-ay1) + (bx2-bx1)*(by2-by1) - intersection
        return intersection / union if union else 0.0

    def update_presence(self, bbox, now=None):
        now = now if now is not None else time.monotonic()
        if bbox is not None:
            if self.association_bbox is not None and self._iou(self.association_bbox, bbox) < 0.15:
                self.reset()
            self.association_bbox = bbox
            self.last_present_at = now
        elif self.last_present_at and now - self.last_present_at >= self.absent_timeout:
            self.reset()

    def reset(self):
        self.result = IdentityResult()
        self.failed_attempts = 0
        self.last_attempt_at = 0.0
        self.association_bbox = None

    def _due(self, now):
        state = self.result.state
        if state == IdentityState.LOCKED_KNOWN:
            return False
        cooldown = self.interval
        if state == IdentityState.UNKNOWN:
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
        if self.result.state == IdentityState.LOCKED_UNKNOWN:
            self.result = IdentityResult(IdentityState.UNVERIFIED, bbox=bbox)
            self.failed_attempts = 0
        self.last_attempt_at = now
        self.frames_submitted += 1
        if _replace_latest(self._inputs, {"crop": crop, "bbox": bbox,
                                         "source_time_s": source_time_s,
                                         "frame_sequence": frame_sequence}):
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
        self.frames_processed += 1
        if self.association_bbox is not None and self._iou(self.association_bbox, latest["bbox"]) < 0.15:
            # Result belongs to a superseded presence association; never lock it
            # onto the person currently visible.
            return self.result
        if latest["known"]:
            # KNOWN is an explicit successful transition; locking is immediate.
            self.result = IdentityResult(IdentityState.KNOWN, latest["name"], latest["confidence"], latest["timestamp"], latest["bbox"], latest["inference_ms"], latest.get("source_time_s"), latest.get("frame_sequence"))
            self.result = IdentityResult(IdentityState.LOCKED_KNOWN, latest["name"], latest["confidence"], latest["timestamp"], latest["bbox"], latest["inference_ms"], latest.get("source_time_s"), latest.get("frame_sequence"))
            self.failed_attempts = 0
        else:
            self.failed_attempts += 1
            state = IdentityState.LOCKED_UNKNOWN if self.failed_attempts >= self.max_unknown_attempts else IdentityState.UNKNOWN
            self.result = IdentityResult(state, None, latest["confidence"], latest["timestamp"], latest["bbox"], latest["inference_ms"], latest.get("source_time_s"), latest.get("frame_sequence"))
        return self.result

    def poll_status(self):
        if self.gallery_status is None:
            try:
                self.gallery_status = self._status.get_nowait()
            except queue.Empty:
                pass
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
