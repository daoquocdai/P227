"""Shared thin standalone CLI wiring for realtime entry points."""

from __future__ import annotations

import argparse
import uuid
from datetime import UTC, datetime

from . import VisionCallbacks, VisionSession, VisionSessionConfig
from .adapters.http_events import EventSender
from .adapters.preview import PreviewAdapter
from .runtime.hardware import BackendResolutionError
from .runtime.source import parse_source


def build_parser(description="Realtime Vision-only fall detection"):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--device", choices=("auto", "cuda", "amd", "intel", "cpu"), default="auto")
    parser.add_argument("--preview", choices=("window", "web", "none"), default="window")
    parser.add_argument("--send-events", action="store_true")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000/api/v1/vision/events")
    parser.add_argument("--camera-id", default="fb61abc0-a568-499e-a95f-9fc824edd3a5")
    parser.add_argument("--camera-location", default="SDA-GCN External AI")
    parser.add_argument("--identity", choices=("on", "off"), default="on")
    parser.add_argument("--source", default="0", help="Camera index (0/1/...) or realtime local video path")
    parser.add_argument("--source-fps", type=float, help="Override invalid/missing video FPS metadata")
    parser.add_argument("--vision-fps", type=float, default=15.0)
    parser.add_argument("--identity-interval", type=float, default=0.5)
    parser.add_argument("--face-det-size", type=int, default=416)
    parser.add_argument("--rebuild-face-cache", action="store_true")
    parser.add_argument("--log-level", choices=("debug", "info", "warning", "error"), default="info")
    parser.add_argument("--identity-debug", action="store_true")
    return parser


def parse_args(argv=None, description="Realtime Vision-only fall detection"):
    args = build_parser(description).parse_args(argv)
    parse_source(args.source)
    if args.source_fps is not None and args.source_fps <= 0:
        raise ValueError("--source-fps must be positive")
    return args


def run_cli(argv=None, *, raw_classifier=False):
    try:
        args = parse_args(
            argv, "Realtime raw Vision-only fall detection" if raw_classifier else "Realtime Vision-only fall detection"
        )
    except ValueError as exc:
        raise SystemExit(f"[Source Error] {exc}")
    sender = EventSender(args.backend_url if args.send_events else None)
    preview = PreviewAdapter(args.preview)
    config = VisionSessionConfig(
        source=args.source,
        source_fps=args.source_fps,
        camera_id=args.camera_id,
        camera_location=args.camera_location,
        device=args.device,
        identity_enabled=args.identity == "on",
        vision_fps=args.vision_fps,
        identity_interval=args.identity_interval,
        face_det_size=args.face_det_size,
        rebuild_face_cache=args.rebuild_face_cache,
        log_level=args.log_level,
        identity_debug=args.identity_debug,
        preview=args.preview,
        raw_classifier=raw_classifier,
    )

    def deliver(event):
        sender.enqueue(
            {
                "event_id": str(uuid.uuid4()),
                "camera_id": config.camera_id,
                "camera_location": config.camera_location,
                "event_type": event.event_type,
                "occurred_at": datetime.now(UTC).isoformat(),
                "confidence": event.confidence,
                "identity_status": event.identity_state or "UNKNOWN",
                "identity_name": event.identity_name,
            }
        )

    session = VisionSession(
        config,
        VisionCallbacks(
            on_event=deliver if sender.enabled else None,
            on_preview=preview.on_preview if args.preview != "none" else None,
        ),
    )
    preview.stop_callback = session.request_stop
    preview.start()
    try:
        session.init_models()
        session.run()
    except BackendResolutionError as exc:
        raise SystemExit(f"[Vision Runtime Error] {exc}")
    finally:
        session.shutdown()
        preview.close()
        sender.close()
